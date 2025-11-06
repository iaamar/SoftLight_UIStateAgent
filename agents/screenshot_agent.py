from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List, Tuple
from utils.logger import get_logger
from utils.browser_controller import BrowserController
import hashlib
import asyncio

logger = get_logger(name="screenshot_agent")


class ScreenshotAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.browser = browser
        self.llm_model = llm_model
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Strategic Screenshot Capture Specialist",
            goal="Capture screenshots at optimal moments with maximum value using reward-based strategy",
            backstory="""Expert in determining when screenshots provide maximum value. Uses reward-based 
            strategy to optimize screenshot capture - only taking screenshots when they capture meaningful 
            state changes, user actions, or workflow milestones. Avoids redundant captures and ensures 
            each screenshot tells a story of the workflow progression.""",
            verbose=True,
            llm=self.llm
        )
        # State tracking for duplicate detection and reward calculation
        self.previous_states: List[Dict[str, Any]] = []
        self.last_screenshot_hash: Optional[str] = None
        self.last_url: Optional[str] = None
        self.navigation_plan: Optional[List[Dict[str, Any]]] = None
        self.reward_scores: List[float] = []  # Track reward scores for optimization
    
    def _get_llm(self, model: str):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if "claude" in model.lower():
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found")
            return ChatAnthropic(model=model, api_key=api_key)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found")
            return ChatOpenAI(model=model, api_key=api_key)
    
    def set_navigation_plan(self, navigation_steps: List[Dict[str, Any]]):
        """Set the navigation plan for strategic screenshot decisions"""
        self.navigation_plan = navigation_steps
        logger.debug(f"Navigation plan set with {len(navigation_steps)} steps")
    
    async def _compute_page_state_hash(self) -> str:
        """Compute a hash of the current page state for duplicate detection"""
        try:
            url = await self.browser.get_url()
            visible_text = await self.browser.get_page_text()
            modals = await self.browser.detect_and_handle_modals()
            modal_text = " ".join([m.get("text", "") for m in modals])
            forms = await self.browser.detect_forms()
            form_count = len(forms)
            
            # Create combined state representation
            state_string = f"{url}|{visible_text[:5000]}|{modal_text}|{form_count}"
            return hashlib.md5(state_string.encode()).hexdigest()
        except Exception as e:
            logger.warning(f"Could not compute page state hash: {e}")
            return hashlib.md5(str(asyncio.get_event_loop().time()).encode()).hexdigest()
    
    async def _calculate_reward_score(
        self,
        step: int,
        action_type: Optional[str] = None,
        action_success: bool = True,
        context: Optional[str] = None
    ) -> float:
        """
        Calculate reward score for taking a screenshot at this moment.
        Higher score = more valuable screenshot.
        Returns score between 0.0 and 1.0
        """
        reward = 0.0
        
        # Base reward for initial state
        if step == 0:
            return 1.0  # Always capture initial state
        
        # Reward based on action type and success
        if action_type:
            action_rewards = {
                "click": 0.8 if action_success else 0.2,  # High reward for successful clicks
                "type": 0.9 if action_success else 0.1,  # Very high for successful typing (form filling)
                "select": 0.7 if action_success else 0.2,
                "navigate": 1.0 if action_success else 0.0,  # Always capture navigation
                "wait": 0.3,  # Low reward for waits
                "scroll": 0.2,  # Very low for scrolls
                "hover": 0.1,  # Minimal reward
            }
            reward += action_rewards.get(action_type, 0.5)
        
        # Reward for state changes
        current_state_hash = await self._compute_page_state_hash()
        if self.last_screenshot_hash and current_state_hash != self.last_screenshot_hash:
            reward += 0.4  # State changed significantly
        
        # Reward for URL changes
        current_url = await self.browser.get_url()
        if self.last_url and current_url != self.last_url:
            reward += 0.5  # URL changed = navigation milestone
        
        # Reward for modal appearance
        modals = await self.browser.detect_and_handle_modals()
        if modals:
            # Check if this is a new modal (not already captured)
            modal_already_seen = False
            for prev_state in self.previous_states[-3:]:
                prev_modals = prev_state.get("modals", [])
                if prev_modals and modals[0].get('text', '')[:50] in str(prev_modals):
                    modal_already_seen = True
                    break
            if not modal_already_seen:
                reward += 0.6  # New modal = important state
        
        # Reward for form interactions
        forms = await self.browser.detect_forms()
        if forms:
            reward += 0.5  # Form visible = important state
        
        # Reward based on navigation plan context
        if self.navigation_plan and step < len(self.navigation_plan):
            current_step_info = self.navigation_plan[step]
            step_action = current_step_info.get("action_type", "")
            
            # Milestone steps get higher reward
            if step_action == "click" and any(word in current_step_info.get("description", "").lower() 
                                            for word in ["create", "submit", "confirm", "save", "finish"]):
                reward += 0.3  # Milestone actions
        
        # Penalty for duplicate states
        if self.last_screenshot_hash and current_state_hash == self.last_screenshot_hash:
            reward *= 0.1  # Heavy penalty for duplicates
        
        # Penalty for wait actions unless state actually changed
        if action_type == "wait" and current_state_hash == self.last_screenshot_hash:
            reward *= 0.2
        
        # Ensure score is between 0 and 1
        return min(1.0, max(0.0, reward))
    
    async def _should_capture_screenshot(
        self,
        step: int,
        action_type: Optional[str] = None,
        action_success: bool = True,
        context: Optional[str] = None,
        force: bool = False
    ) -> Tuple[bool, float, str]:
        """
        Decide whether to capture screenshot based on reward-based strategy.
        Returns: (should_capture, reward_score, reason)
        """
        if force:
            return (True, 1.0, "forced")
        
        # Always capture initial state
        if step == 0:
            return (True, 1.0, "initial_state")
        
        # Calculate reward score
        reward_score = await self._calculate_reward_score(step, action_type, action_success, context)
        
        # Decision threshold: only capture if reward > 0.5 (moderate value)
        # But be more lenient for high-value actions (type, click milestones)
        threshold = 0.5
        if action_type in ["type", "navigate"]:
            threshold = 0.4  # Lower threshold for high-value actions
        elif action_type == "wait":
            threshold = 0.7  # Higher threshold for low-value actions
        
        should_capture = reward_score >= threshold
        
        # Generate reason
        if should_capture:
            reasons = []
            if reward_score >= 0.8:
                reasons.append("high_value")
            if action_type in ["type", "navigate"]:
                reasons.append(f"critical_{action_type}")
            current_url = await self.browser.get_url()
            if current_url != self.last_url:
                reasons.append("url_change")
            modals = await self.browser.detect_and_handle_modals()
            if modals:
                reasons.append("modal_appeared")
            reason = "_".join(reasons) if reasons else "state_change"
        else:
            reason = "low_reward"
        
        return (should_capture, reward_score, reason)
    
    async def _identify_focus_elements(self, context: Optional[str] = None, action_type: Optional[str] = None) -> List[str]:
        """Identify which elements to focus on/highlight in the screenshot"""
        focus_elements = []
        
        # Check for visible modals (highest priority)
        modals = await self.browser.detect_and_handle_modals()
        if modals:
            focus_elements.append("[role='dialog']")
            focus_elements.append("[aria-modal='true']")
            logger.info("Focusing on modal/dialog")
            return focus_elements
        
        # Check for forms
        forms = await self.browser.detect_forms()
        if forms:
            focus_elements.append("form")
            logger.info("Focusing on form")
            return focus_elements
        
        # If context mentions specific elements, try to find them
        if context:
            context_lower = context.lower()
            import re
            
            # Extract element names from context
            quoted_elements = re.findall(r'[\'"]([^\'"]+)[\'"]', context)
            
            # Common patterns
            if "code" in context_lower or any("code" in e.lower() for e in quoted_elements):
                focus_elements.extend([
                    "summary[aria-label*='Code']",
                    "button:has-text('Code')",
                    "[data-testid='code-button']"
                ])
            
            if "create" in context_lower or "new" in context_lower:
                focus_elements.extend([
                    "[data-testid*='create']",
                    "[aria-label*='create' i]",
                    "button:has-text('Create')",
                    "button:has-text('New')"
                ])
            
            # For quoted elements, try to find buttons/links with that text
            for element_name in quoted_elements:
                if len(element_name) > 2:
                    focus_elements.extend([
                        f"button:has-text('{element_name}')",
                        f"[aria-label*='{element_name}' i]",
                        f"a:has-text('{element_name}')"
                    ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_elements = []
        for elem in focus_elements:
            if elem not in seen:
                seen.add(elem)
                unique_elements.append(elem)
        
        return unique_elements[:5]  # Limit to 5 selectors
    
    async def capture_screenshot(
        self,
        app: str,
        task: str,
        step: int,
        context: Optional[str] = None,
        force: bool = False,
        action_type: Optional[str] = None,
        action_success: bool = True
    ) -> Optional[str]:
        """
        Capture screenshot using reward-based strategy.
        Only captures when reward score exceeds threshold.
        
        Args:
            app: Application name
            task: Task name
            step: Step number
            context: Context about what just happened
            force: Force capture even if reward is low
            action_type: Type of action that just occurred (click, type, etc.)
            action_success: Whether the action succeeded
        
        Returns:
            Screenshot path if captured, None if skipped (low reward)
        """
        logger.log_agent_start("ScreenshotAgent", task=f"Step {step}")
        
        try:
            # Check if browser/page is available
            try:
                if not self.browser.page or self.browser.page.is_closed():
                    logger.warning(f"Browser page is closed - cannot capture screenshot at step {step}")
                    return None
            except Exception:
                logger.warning(f"Cannot check browser state - browser may be closed")
                return None
            
            # Wait for page to stabilize
            await self.browser.wait_for_stable_page(stability_time=0.5, max_wait=3.0)
            
            # Make strategic decision using reward-based approach
            should_capture, reward_score, reason = await self._should_capture_screenshot(
                step=step,
                action_type=action_type,
                action_success=action_success,
                context=context,
                force=force
            )
            
            if not should_capture:
                logger.info(f"⏭️ Skipping screenshot at step {step} - reward score {reward_score:.2f} < threshold (reason: {reason})")
                logger.log_agent_end("ScreenshotAgent", success=True)
                return None
            
            logger.info(f"📸 Capturing screenshot at step {step} - reward score: {reward_score:.2f} (reason: {reason})")
            
            # Identify focus elements for smart cropping
            focus_elements = await self._identify_focus_elements(context, action_type)
            
            # Determine screenshot strategy
            use_full_page = False
            highlight_elements = []
            
            if focus_elements:
                highlight_elements = focus_elements
                logger.info(f"Using smart crop focusing on: {focus_elements[0]}")
            else:
                logger.info("No specific focus elements - capturing viewport")
            
            # Capture the screenshot
            screenshot_path = await self.browser.smart_screenshot(
                app=app,
                task=task,
                step=step,
                full_page=use_full_page,
                highlight_elements=highlight_elements if highlight_elements else None
            )
            
            # Update state tracking
            try:
                current_url = await self.browser.get_url()
                current_hash = await self._compute_page_state_hash()
                modals = await self.browser.detect_and_handle_modals()
                
                self.last_screenshot_hash = current_hash
                self.last_url = current_url
                self.reward_scores.append(reward_score)
                
                self.previous_states.append({
                    "step": step,
                    "url": current_url,
                    "hash": current_hash,
                    "context": context,
                    "reward_score": reward_score,
                    "reason": reason,
                    "action_type": action_type,
                    "screenshot_path": screenshot_path,
                    "modals": modals
                })
                
                # Keep only last 10 states for efficiency
                if len(self.previous_states) > 10:
                    self.previous_states = self.previous_states[-10:]
            except Exception as state_error:
                logger.warning(f"Could not update state tracking: {state_error}")
            
            logger.info(f"✅ Screenshot captured: {screenshot_path} (reward: {reward_score:.2f})")
            logger.log_agent_end("ScreenshotAgent", success=True)
            return screenshot_path
            
        except Exception as e:
            error_msg = str(e).lower()
            if "closed" in error_msg or "target page" in error_msg:
                logger.warning(f"Browser/context closed - cannot capture screenshot at step {step}: {e}")
                logger.log_agent_end("ScreenshotAgent", success=False)
                return None
            else:
                logger.log_error(e, context={"agent": "ScreenshotAgent", "step": step})
                logger.log_agent_end("ScreenshotAgent", success=False)
                raise
    
    def get_captured_states(self) -> List[Dict[str, Any]]:
        """Get all captured states for analysis"""
        return self.previous_states
    
    def get_average_reward_score(self) -> float:
        """Get average reward score for optimization analysis"""
        if not self.reward_scores:
            return 0.0
        return sum(self.reward_scores) / len(self.reward_scores)
    
    def reset_state(self):
        """Reset state tracking (useful between different tasks)"""
        self.previous_states = []
        self.last_screenshot_hash = None
        self.last_url = None
        self.reward_scores = []
        self.navigation_plan = None
        logger.info("Screenshot agent state reset")

