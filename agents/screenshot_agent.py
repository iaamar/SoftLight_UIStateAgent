from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from utils.browser_controller import BrowserController
import hashlib
import asyncio

logger = get_logger(name="screenshot_agent")


class ScreenshotAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Smart Screenshot Capture Specialist",
            goal="Capture focused, non-duplicate screenshots showing only relevant UI state changes",
            backstory="""Expert in identifying meaningful UI changes and capturing focused screenshots. 
            Avoids duplicates and always crops to show only the relevant UI state clearly.""",
            verbose=True,
            llm=self.llm
        )
        # State tracking for duplicate detection
        self.previous_states: List[Dict[str, Any]] = []
        self.last_screenshot_hash: Optional[str] = None
        self.last_url: Optional[str] = None
        self.last_visible_text_hash: Optional[str] = None
    
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
    
    async def _compute_page_state_hash(self) -> str:
        """Compute a hash of the current page state for duplicate detection"""
        try:
            # Get key state indicators
            url = await self.browser.get_url()
            visible_text = await self.browser.get_page_text()
            
            # Check for modals/dialogs
            modals = await self.browser.detect_and_handle_modals()
            modal_text = " ".join([m.get("text", "") for m in modals])
            
            # Get form state
            forms = await self.browser.detect_forms()
            form_count = len(forms)
            
            # Create combined state representation
            state_string = f"{url}|{visible_text[:5000]}|{modal_text}|{form_count}"
            
            # Hash it
            return hashlib.md5(state_string.encode()).hexdigest()
        except Exception as e:
            logger.warning(f"Could not compute page state hash: {e}")
            return hashlib.md5(str(asyncio.get_event_loop().time()).encode()).hexdigest()
    
    async def _detect_meaningful_change(self) -> Dict[str, Any]:
        """Detect if there's a meaningful change worth capturing - improved duplicate detection"""
        current_url = await self.browser.get_url()
        current_state_hash = await self._compute_page_state_hash()
        
        # Detect what changed
        changes = {
            "has_change": False,
            "url_changed": False,
            "content_changed": False,
            "modal_appeared": False,
            "form_detected": False,
            "change_description": ""
        }
        
        # First screenshot always captures
        if not self.last_screenshot_hash:
            changes["has_change"] = True
            changes["change_description"] = "Initial state"
            return changes
        
        # Check URL change (always significant)
        if self.last_url and current_url != self.last_url:
            changes["url_changed"] = True
            changes["has_change"] = True
            changes["change_description"] = f"URL changed"
            return changes
        
        # Check content change - only if hash actually differs
        if current_state_hash != self.last_screenshot_hash:
            changes["content_changed"] = True
            changes["has_change"] = True
            changes["change_description"] = "Page content changed"
            
            # Check for NEW modals (not the same one we've seen before)
            modals = await self.browser.detect_and_handle_modals()
            if modals:
                # Check if we've already captured this modal before
                modal_text = modals[0].get('text', '')[:100]  # First 100 chars for comparison
                
                # Look in previous states to see if this modal was already captured
                modal_already_seen = False
                for prev_state in self.previous_states[-3:]:  # Check last 3 states
                    prev_context = prev_state.get("context", "")
                    if modal_text and modal_text in prev_context:
                        modal_already_seen = True
                        break
                
                if not modal_already_seen:
                    changes["modal_appeared"] = True
                    changes["change_description"] = f"New modal/dialog detected"
                else:
                    # Same modal - don't treat as new change
                    logger.debug(f"Modal already captured in previous state, not treating as new change")
            else:
                # Check for forms (only if no modal)
                forms = await self.browser.detect_forms()
                if forms:
                    changes["form_detected"] = True
                    changes["change_description"] = f"Form with {len(forms[0].get('fields', []))} fields detected"
        else:
            # Same hash = truly identical state
            logger.debug(f"No change detected - same state hash: {current_state_hash[:8]}")
        
        return changes
    
    async def _identify_focus_elements(self, context: Optional[str] = None) -> List[str]:
        """Identify which elements to focus on/highlight in the screenshot"""
        focus_elements = []
        
        # Check for visible modals (highest priority)
        modals = await self.browser.detect_and_handle_modals()
        if modals:
            focus_elements.append("[role='dialog']")
            focus_elements.append("[aria-modal='true']")
            logger.info("Focusing on modal/dialog")
            return focus_elements  # Modals take priority
        
        # Check for forms
        forms = await self.browser.detect_forms()
        if forms:
            focus_elements.append("form")
            logger.info("Focusing on form")
            return focus_elements
        
        # If context mentions specific elements, try to find them
        if context:
            context_lower = context.lower()
            
            # Extract element names from context (look for quoted text or specific keywords)
            import re
            
            # Look for quoted element names (e.g., "Code" button, 'Clone URL')
            quoted_elements = re.findall(r'[\'"]([^\'"]+)[\'"]', context)
            
            # Common GitHub/clone-related selectors
            if "code" in context_lower or any("code" in e.lower() for e in quoted_elements):
                # GitHub Code button dropdown
                focus_elements.extend([
                    "summary[aria-label*='Code']",
                    "button:has-text('Code')",
                    "[data-testid='code-button']",
                    ".Button--primary:has-text('Code')"
                ])
            
            if "clone" in context_lower or "copy" in context_lower:
                # Clone/Copy buttons and URLs
                focus_elements.extend([
                    "button:has-text('Copy')",
                    "button[aria-label*='copy' i]",
                    "[data-clipboard-target]",
                    "input[readonly][value*='github.com']",
                    ".Box:has(input[readonly])",
                    "button[aria-label*='Copy URL']",
                    "button:has-text('Clone')"
                ])
            
            if "https" in context_lower:
                # HTTPS clone URL field
                focus_elements.extend([
                    "input[readonly][value*='https://']",
                    ".Box:has(input[readonly][value*='https://'])",
                    "[data-testid='clone-url']"
                ])
            
            # Look for buttons mentioned in context
            if "button" in context_lower or "click" in context_lower:
                # Try to find recently interacted buttons
                focus_elements.extend([
                    "button:focus",
                    "button:hover",
                    "[role='button']:focus"
                ])
            
            # Look for specific UI patterns
            if "create" in context_lower or "new" in context_lower:
                focus_elements.extend([
                    "[data-testid*='create']",
                    "[aria-label*='create' i]",
                    "button:has-text('Create')",
                    "button:has-text('New')"
                ])
            
            if "filter" in context_lower or "search" in context_lower:
                focus_elements.extend([
                    "[role='searchbox']",
                    "[data-testid*='filter']",
                    "input[type='search']"
                ])
            
            # For any quoted element names, try to find buttons/links with that text
            for element_name in quoted_elements:
                if len(element_name) > 2:  # Ignore very short names
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
        
        return unique_elements[:5]  # Limit to 5 selectors to avoid performance issues
    
    async def capture_screenshot(
        self, 
        app: str, 
        task: str, 
        step: int, 
        context: Optional[str] = None,
        force: bool = False
    ) -> Optional[str]:
        """
        Capture a smart, focused screenshot only if there's a meaningful change.
        
        Args:
            app: Application name
            task: Task name
            step: Step number
            context: Context about what just happened
            force: Force capture even if no change detected
        
        Returns:
            Screenshot path if captured, None if skipped (duplicate)
        """
        logger.log_agent_start("ScreenshotAgent", task=f"Step {step}")
        
        try:
            # Check if browser/page is still available before proceeding
            try:
                if not self.browser.page or self.browser.page.is_closed():
                    logger.warning(f"⚠️ Browser page is closed - cannot capture screenshot at step {step}")
                    logger.log_agent_end("ScreenshotAgent", success=False)
                    return None
            except Exception as check_error:
                # If check fails, browser might be closed
                logger.warning(f"⚠️ Cannot check browser state - browser may be closed: {check_error}")
                logger.log_agent_end("ScreenshotAgent", success=False)
                return None
            
            # Wait for page to stabilize
            await self.browser.wait_for_stable_page(stability_time=0.5, max_wait=3.0)
            
            # Detect if there's a meaningful change
            # Balance: Capture meaningful actions but avoid true duplicates
            if not force:
                changes = await self._detect_meaningful_change()
                current_url = await self.browser.get_url()
                current_hash = await self._compute_page_state_hash()
                
                # Check if URL changed (always capture on URL change)
                url_changed = current_url != self.last_url
                
                # Always capture initial state
                if step == 0:
                    logger.info(f"📸 Capturing initial state at step {step}")
                    should_capture = True
                elif not self.last_screenshot_hash:
                    # No previous screenshot - always capture
                    logger.info(f"📸 No previous screenshot - capturing at step {step}")
                    should_capture = True
                elif url_changed:
                    # URL changed - always capture
                    logger.info(f"📸 Change detected: URL changed")
                    should_capture = True
                elif changes["has_change"]:
                    # Content actually changed - capture it
                    logger.info(f"📸 Change detected: {changes['change_description']}")
                    should_capture = True
                elif context:
                    # Check if this is a meaningful action that should always be captured
                    context_lower = context.lower()
                    
                    # Extract action type from context - prioritize meaningful actions
                    action_type = None
                    action_keywords = []
                    
                    # Prioritize click/type/select over wait - these are user actions
                    # Check for click actions (includes "click on", "click the", etc.)
                    if "click" in context_lower and "wait" not in context_lower:  # Make sure "click" in wait doesn't match
                        action_type = "click"
                        action_keywords = ["click", "button"]
                        logger.debug(f"Detected click action from: {context[:50]}")
                    # Check for type/enter actions - very permissive, check "enter text" first
                    elif ("enter text" in context_lower or 
                          (("enter" in context_lower or "type" in context_lower) and "text" in context_lower)):
                        action_type = "type"
                        action_keywords = ["type", "enter", "text"]
                        logger.debug(f"Detected type action from: {context[:50]}")
                    elif "enter" in context_lower or "type" in context_lower:
                        # Catch any remaining enter/type patterns (includes "Enter text")
                        action_type = "type"
                        action_keywords = ["type", "enter"]
                        logger.debug(f"Detected type action from: {context[:50]}")
                    elif "select" in context_lower:
                        action_type = "select"
                        action_keywords = ["select"]
                        logger.debug(f"Detected select action from: {context[:50]}")
                    elif "wait" in context_lower:
                        action_type = "wait"
                        logger.debug(f"Detected wait action from: {context[:50]}")
                        # For wait steps, be more lenient - capture if there's any hint of change
                        # or if content hash actually changed
                        if changes["has_change"]:
                            logger.info(f"📸 Capturing wait step: {context[:50]} - change detected")
                            should_capture = True
                        elif len(self.previous_states) >= 2:
                            # Capture wait if it's been a few steps since last screenshot
                            logger.info(f"📸 Capturing wait step: {context[:50]} - enough steps passed")
                            should_capture = True
                        else:
                            logger.info(f"⏭️ Skipping wait step {step} - no change and too recent")
                            logger.log_agent_end("ScreenshotAgent", success=True)
                            return None
                    
                    # Skip wait handling if we already processed it above
                    if action_type == "wait" and should_capture:
                        pass  # Already handled
                    # Always capture meaningful actions (click, type, select) even if state is similar
                    elif action_type in ["click", "type", "select"]:
                        # Only skip if it's the EXACT same action on EXACT same element with identical hash from immediately previous step
                        # Extract the element name from context to compare
                        recent_exact_duplicate = False
                        if len(self.previous_states) > 0:
                            last_state = self.previous_states[-1]
                            prev_hash = last_state.get("hash")
                            prev_context = last_state.get("context", "").lower()
                            
                            # Normalize contexts by removing metadata suffixes
                            context_normalized = context_lower.replace(" (a popup or menu appeared)", "").replace(" (entered information)", "").strip()
                            prev_context_normalized = prev_context.replace(" (a popup or menu appeared)", "").replace(" (entered information)", "").strip()
                            
                            # Only skip if it's EXACTLY the same text AND same hash
                            # Don't check for same element - different elements with same action should be captured
                            if prev_hash == current_hash and context_normalized == prev_context_normalized:
                                recent_exact_duplicate = True
                        
                        if recent_exact_duplicate:
                            logger.info(f"⏭️ Skipping duplicate screenshot at step {step} - exact same action text and identical state")
                            logger.log_agent_end("ScreenshotAgent", success=True)
                            return None
                        else:
                            # Different action text OR different state - always capture meaningful actions
                            logger.info(f"📸 Capturing {action_type} action: {context[:50]} (prev: {len(self.previous_states)} states)")
                            should_capture = True
                    elif action_type == "wait":
                        # Wait actions already handled above - skip this section
                        pass
                    else:
                        # Unknown action type or no clear action
                        if current_hash == self.last_screenshot_hash:
                            logger.info(f"⏭️ Skipping duplicate screenshot at step {step} - identical state, unclear action")
                            logger.log_agent_end("ScreenshotAgent", success=True)
                            return None
                        else:
                            logger.info(f"📸 Capturing step {step} - different state detected")
                            should_capture = True
                else:
                    # No context, no change - skip if identical
                    if current_hash == self.last_screenshot_hash:
                        logger.info(f"⏭️ Skipping duplicate screenshot at step {step} - identical state, no context")
                        logger.log_agent_end("ScreenshotAgent", success=True)
                        return None
                    else:
                        should_capture = True
                
                if not should_capture:
                    logger.info(f"⏭️ Skipping duplicate screenshot at step {step}")
                    logger.log_agent_end("ScreenshotAgent", success=True)
                    return None
            
            # Identify what to focus on
            focus_elements = await self._identify_focus_elements(context)
            
            # Determine if we should use full page or smart crop
            use_full_page = False
            highlight_elements = []
            
            if focus_elements:
                # Use smart cropping with highlights
                highlight_elements = focus_elements
                logger.info(f"Using smart crop focusing on: {focus_elements[0]}")
            else:
                # No specific focus - capture viewport only (not full page)
                logger.info("No specific focus elements - capturing viewport")
            
            # Capture the screenshot
            screenshot_path = await self.browser.smart_screenshot(
                app=app,
                task=task,
                step=step,
                full_page=use_full_page,
                highlight_elements=highlight_elements if highlight_elements else None
            )
            
            # Update state tracking (only if screenshot was successfully captured)
            try:
                self.last_screenshot_hash = await self._compute_page_state_hash()
                self.last_url = await self.browser.get_url()
                
                self.previous_states.append({
                    "step": step,
                    "url": self.last_url,
                    "hash": self.last_screenshot_hash,
                    "context": context,
                    "screenshot_path": screenshot_path
                })
            except Exception as state_error:
                # If state tracking fails, log but don't fail the screenshot
                logger.warning(f"⚠️ Could not update state tracking: {state_error}")
            
            logger.info(f"✅ Screenshot captured: {screenshot_path}")
            logger.log_agent_end("ScreenshotAgent", success=True)
            return screenshot_path
            
        except Exception as e:
            error_msg = str(e).lower()
            # Check if browser/context is closed - this is expected in some scenarios
            if "closed" in error_msg or "target page" in error_msg or "browser" in error_msg and "closed" in error_msg:
                logger.warning(f"⚠️ Browser/context closed - cannot capture screenshot at step {step}: {e}")
                logger.log_agent_end("ScreenshotAgent", success=False)
                return None  # Return None instead of raising to allow workflow to continue
            else:
                # For other errors, log and raise
                logger.log_error(e, context={"agent": "ScreenshotAgent", "step": step})
                logger.log_agent_end("ScreenshotAgent", success=False)
                raise
    
    def get_captured_states(self) -> List[Dict[str, Any]]:
        """Get all captured states for analysis"""
        return self.previous_states
    
    def reset_state(self):
        """Reset state tracking (useful between different tasks)"""
        self.previous_states = []
        self.last_screenshot_hash = None
        self.last_url = None
        self.last_visible_text_hash = None
        logger.info("Screenshot agent state reset")
