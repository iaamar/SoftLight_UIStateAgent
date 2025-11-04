from typing import TypedDict, List, Dict, Any, Optional, Callable, Awaitable
from utils.logger import get_logger
from utils.browser_controller import BrowserController
from agents.ui_navigator_agent import UINavigatorAgent
from agents.screenshot_agent import ScreenshotAgent
from agents.state_validator_agent import StateValidatorAgent
from agents.context_sync_agent import ContextSyncAgent
import asyncio
import time
import json
from pathlib import Path

logger = get_logger(name="workflow")


class WorkflowState:
    def __init__(self):
        self.task_query: str = ""
        self.app_url: str = ""
        self.app_name: str = ""
        self.task_name: str = ""
        self.navigation_steps: List[Dict[str, Any]] = []
        self.current_step: int = 0
        self.screenshots: List[str] = []
        self.screenshot_to_step_map: Dict[str, int] = {}  # Map screenshot path to step index
        self.step_descriptions: List[str] = []
        self.ui_states: List[Dict[str, Any]] = []  # Comprehensive UI state captures
        self.state_valid: bool = True
        self.completed: bool = False
        self.error: Optional[str] = None
        self.execution_log: List[Dict[str, Any]] = []  # Detailed execution log
        self.detected_modals: List[Dict[str, Any]] = []
        self.form_interactions: List[Dict[str, Any]] = []


class AgentWorkflow:
    def __init__(
        self,
        browser: BrowserController,
        llm_model: str = "claude-sonnet-4-5-20250929",
        max_steps: int = 50,
        retry_attempts: int = 3,
        capture_metadata: bool = True,
        progress_callback: Optional[Callable[[int, int, str, Optional[str]], Awaitable[None]]] = None
    ):
        self.browser = browser
        self.llm_model = llm_model
        self.max_steps = max_steps
        self.retry_attempts = retry_attempts
        self.capture_metadata = capture_metadata
        self.progress_callback = progress_callback
        
        self.navigator = UINavigatorAgent(browser, llm_model)
        self.screenshot = ScreenshotAgent(browser, llm_model)
        self.validator = StateValidatorAgent(browser, llm_model)
        self.context_sync = ContextSyncAgent(llm_model)
    
    def _log_execution(self, state: WorkflowState, event: str, details: Dict[str, Any]):
        """Log execution details for debugging and analysis"""
        log_entry = {
            "timestamp": time.time(),
            "step": state.current_step,
            "event": event,
            "details": details,
            "url": details.get("url", ""),
            "success": details.get("success", True)
        }
        state.execution_log.append(log_entry)
        logger.debug(f"Execution log: {event} - {details}")
    
    async def _capture_ui_state(self, state: WorkflowState, context: str):
        """Capture comprehensive UI state including non-URL states"""
        try:
            ui_state = await self.browser.capture_full_workflow_state()
            ui_state["context"] = context
            ui_state["step"] = state.current_step
            
            # Detect and log any modals
            modals = await self.browser.detect_and_handle_modals()
            if modals:
                ui_state["modals"] = modals
                state.detected_modals.extend(modals)
            
            # Detect forms
            forms = await self.browser.detect_forms()
            if forms:
                ui_state["forms"] = forms
            
            state.ui_states.append(ui_state)
            
            self._log_execution(state, "ui_state_capture", {
                "context": context,
                "has_modals": len(modals) > 0,
                "has_forms": len(forms) > 0,
                "url": ui_state["url"]
            })
            
        except Exception as e:
            logger.error(f"Failed to capture UI state: {e}")
            self._log_execution(state, "ui_state_capture_error", {"error": str(e)})
    
    async def _navigate_step_enhanced(self, state: WorkflowState):
        """Enhanced navigation with better error handling and state capture"""
        logger.log_action("navigate_step_enhanced", {"step": state.current_step})
        
        try:
            if state.current_step == 0:
                # Initial navigation planning
                if self.progress_callback:
                    await self.progress_callback(0, 0, "Planning navigation steps...", "analyzing")
                navigation_steps = await self.navigator.navigate_to_task(
                    state.task_query,
                    state.app_url
                )
                state.navigation_steps = navigation_steps
                logger.info(f"Generated {len(navigation_steps)} navigation steps")
                if self.progress_callback:
                    await self.progress_callback(0, len(navigation_steps), "Navigation plan created", "planning_complete")
                
                if len(navigation_steps) == 0:
                    logger.warning("No navigation steps generated - task may already be complete")
                    await self._capture_ui_state(state, "task_complete_initial")
                    state.completed = True
                    return
            
            if state.current_step < len(state.navigation_steps):
                step = state.navigation_steps[state.current_step]
                await self._execute_navigation_step(state, step)
            else:
                logger.info(f"All navigation steps completed ({state.current_step}/{len(state.navigation_steps)})")
                state.completed = True
            
        except Exception as e:
            logger.log_error(e, context={"step": "navigate", "step_number": state.current_step})
            self._log_execution(state, "navigation_error", {"error": str(e), "step": state.current_step})
            
            # Try to recover
            if state.current_step < len(state.navigation_steps) - 1:
                state.current_step += 1
            else:
                state.completed = True
                state.error = str(e)
    
    async def _execute_navigation_step(self, state: WorkflowState, step: Dict[str, Any]):
        """Execute a single navigation step with enhanced error handling"""
        action_type = step.get("action_type", "click")
        selector = step.get("selector", "").strip()
        description = step.get("description", "")
        
        logger.info(f"Executing step {state.current_step + 1}: {action_type} on '{selector}' - {description}")
        
        # Send progress update
        if self.progress_callback:
            await self.progress_callback(
                state.current_step + 1,
                len(state.navigation_steps),
                description,
                f"{action_type}: {description[:50]}"
            )
        
        # Pre-execution state capture for modals/dynamic content
        if action_type == "click" and any(word in description.lower() for word in ["new", "create", "add", "open"]):
            await self._capture_ui_state(state, f"pre_{action_type}_{description}")
        
        try:
            # Execute based on action type
            if action_type == "click":
                await self._execute_click(state, selector, description)
            elif action_type == "type":
                await self._execute_type(state, selector, step.get("text", ""), description)
            elif action_type == "wait":
                await self._execute_wait(state, step.get("wait_time", 2))
            elif action_type == "select":
                await self._execute_select(state, selector, step.get("options", ""))
            elif action_type == "hover":
                await self._execute_hover(state, selector)
            elif action_type == "scroll":
                await self._execute_scroll(state, selector)
            elif action_type == "navigate":
                await self._execute_navigate(state, step.get("url", state.app_url))
            
            # Post-execution state capture
            await self._capture_ui_state(state, f"post_{action_type}_{description}")
            
            self._log_execution(state, f"step_executed_{action_type}", {
                "selector": selector,
                "description": description,
                "success": True
            })
            
            state.current_step += 1
            
        except Exception as e:
            logger.error(f"Error executing {action_type}: {e}")
            self._log_execution(state, f"step_failed_{action_type}", {
                "selector": selector,
                "description": description,
                "error": str(e),
                "success": False
            })
            
            # Try alternative approaches
            if action_type == "click" and selector:
                await self._try_alternative_click(state, selector, description)
            
            state.current_step += 1
    
    async def _execute_click(self, state: WorkflowState, selector: str, description: str):
        """Execute click with retry and alternative strategies"""
        if not selector:
            raise ValueError("Empty selector for click action")
        
        # First attempt with standard click
        try:
            await self.browser.click(selector, retry=True)
            await self.browser.wait_for_stable_page()
            
            # Wait a bit for dropdowns/menus to appear after click
            await asyncio.sleep(0.5)
            
            # Check if a dropdown/menu appeared (common after "create", "new", "add" buttons)
            if any(word in description.lower() for word in ["create", "new", "add", "open", "show"]):
                # Wait for potential dropdown/menu to appear
                await asyncio.sleep(0.5)
                # Check for visible menus/dropdowns
                menu_selectors = [
                    "[role='menu']:visible",
                    "[role='listbox']:visible",
                    ".dropdown-menu:visible",
                    "[class*='menu']:visible",
                    "[class*='dropdown']:visible",
                ]
                for menu_sel in menu_selectors:
                    try:
                        menu = await self.browser.page.query_selector(menu_sel)
                        if menu:
                            logger.info(f"Dropdown/menu detected after click: {menu_sel}")
                            break
                    except:
                        continue
        except Exception as e:
            logger.warning(f"Standard click failed: {e}")
            
            # Try finding element by text from description
            if description:
                text_match = self._extract_text_from_description(description)
                if text_match:
                    alt_selector = await self.browser.find_element_by_text(text_match)
                    if alt_selector:
                        logger.info(f"Found alternative selector: {alt_selector}")
                        await self.browser.click(alt_selector)
                        await self.browser.wait_for_stable_page()
                        return
            
            raise e
    
    async def _execute_type(self, state: WorkflowState, selector: str, text: str, description: str):
        """Execute type action with form interaction tracking"""
        if not selector:
            raise ValueError("Empty selector for type action")
        
        if not text:
            logger.warning("No text provided for type action")
            return
        
        await self.browser.type(selector, text)
        
        # Track form interaction
        state.form_interactions.append({
            "selector": selector,
            "text": text,
            "description": description,
            "timestamp": time.time()
        })
    
    async def _execute_wait(self, state: WorkflowState, wait_time: int):
        """Execute wait with dynamic content detection"""
        logger.info(f"Waiting for {wait_time} seconds")
        
        # Instead of just sleeping, monitor for changes
        start_time = time.time()
        initial_html_length = len(await self.browser.get_page_html())
        
        while time.time() - start_time < wait_time:
            await asyncio.sleep(0.5)
            
            # Check for new modals
            modals = await self.browser.detect_and_handle_modals()
            if modals and len(modals) > len(state.detected_modals):
                logger.info("New modal detected during wait")
                state.detected_modals = modals
                break
            
            # Check for significant DOM changes
            current_html_length = len(await self.browser.get_page_html())
            if abs(current_html_length - initial_html_length) > 1000:
                logger.info("Significant DOM change detected during wait")
                break
    
    async def _execute_select(self, state: WorkflowState, selector: str, option: str):
        """Execute select action for dropdowns"""
        if not selector:
            raise ValueError("Empty selector for select action")
        
        await self.browser.page.select_option(selector, option)
    
    async def _execute_hover(self, state: WorkflowState, selector: str):
        """Execute hover action"""
        if not selector:
            raise ValueError("Empty selector for hover action")
        
        await self.browser.page.hover(selector)
        await asyncio.sleep(0.5)  # Brief wait for hover effects
    
    async def _execute_scroll(self, state: WorkflowState, selector: str):
        """Execute scroll action"""
        if selector:
            await self.browser.page.evaluate(f"document.querySelector('{selector}').scrollIntoView()")
        else:
            # Scroll to bottom
            await self.browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    
    async def _execute_navigate(self, state: WorkflowState, url: str):
        """Execute navigation to new URL"""
        await self.browser.navigate(url)
        await self.browser.wait_for_stable_page()
    
    async def _try_alternative_click(self, state: WorkflowState, selector: str, description: str):
        """Try alternative methods to click an element"""
        # Method 1: JavaScript click
        try:
            await self.browser.page.evaluate(f"document.querySelector('{selector}').click()")
            logger.info("JavaScript click successful")
            return
        except:
            pass
        
        # Method 2: Find by partial text
        try:
            elements = await self.browser.page.query_selector_all(f"*:has-text('{description}')")
            for element in elements[:3]:  # Try first 3 matches
                if await element.is_visible():
                    await element.click()
                    logger.info("Click by text match successful")
                    return
        except:
            pass
        
        logger.warning(f"All alternative click methods failed for {selector}")
    
    def _extract_text_from_description(self, description: str) -> Optional[str]:
        """Extract clickable text from description"""
        import re
        # Look for quoted text
        match = re.search(r'["\']([^"\']+)["\']', description)
        if match:
            return match.group(1)
        
        # Look for specific patterns
        patterns = [
            r'(?:click|press|select)\s+(?:the\s+)?(\w+(?:\s+\w+)?)',
            r'(?:on|the)\s+(\w+(?:\s+\w+)?)\s+(?:button|link|tab)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    async def _screenshot_step_enhanced(self, state: WorkflowState):
        """Smart screenshot with duplicate detection - always track steps, only capture unique screenshots"""
        logger.log_action("screenshot_step_enhanced", {"step": state.current_step})
        
        try:
            # Generate context description for smart cropping
            context = await self._generate_step_description(state)
            
            # ALWAYS add step description (so all steps are visible to user)
            # But only add screenshot if it's not a duplicate
            state.step_descriptions.append(context)
            
            # Send progress update for screenshot capture
            if self.progress_callback:
                await self.progress_callback(
                    state.current_step + 1,
                    len(state.navigation_steps) if state.navigation_steps else 0,
                    f"Capturing screenshot: {context[:50]}",
                    "capturing_screenshot"
                )
            
            # Use the smart screenshot agent (handles duplicate detection & cropping)
            screenshot_path = await self.screenshot.capture_screenshot(
                app=state.app_name,
                task=state.task_name,
                step=state.current_step,
                context=context,
                force=False  # Allow duplicate detection
            )
            
            # Only add screenshot path if actually captured (not skipped as duplicate)
            if screenshot_path:
                state.screenshots.append(screenshot_path)
                # Map screenshot to the step index it corresponds to
                step_index = len(state.step_descriptions) - 1  # Current step description index
                state.screenshot_to_step_map[screenshot_path] = step_index
                self._log_execution(state, "screenshot_captured", {
                    "path": screenshot_path,
                    "description": context,
                    "smart_cropped": True,
                    "step": state.current_step,
                    "step_index": step_index
                })
            else:
                # Screenshot was skipped (duplicate) - but step description is already added
                logger.info(f"⏭️ Screenshot skipped at step {state.current_step} - duplicate/identical state (step still tracked)")
                self._log_execution(state, "screenshot_skipped", {
                    "reason": "duplicate_state",
                    "step": state.current_step,
                    "description": context
                })
            
        except Exception as e:
            logger.log_error(e, context={"step": "screenshot_enhanced"})
            # Even on error, ensure step description is tracked
            if len(state.step_descriptions) <= state.current_step:
                try:
                    context = await self._generate_step_description(state)
                    state.step_descriptions.append(context)
                except:
                    state.step_descriptions.append(f"Step {state.current_step} (error: {str(e)[:50]})")
    
    async def _generate_step_description(self, state: WorkflowState) -> str:
        """Generate user-friendly step description in simple, guide-like language"""
        if state.current_step == 0:
            return f"Start: Open the application"
        
        # Get info about what just happened
        if state.current_step > 0 and state.current_step <= len(state.navigation_steps):
            prev_step = state.navigation_steps[state.current_step - 1]
            action = prev_step.get("action_type", "")
            desc = prev_step.get("description", "")
            
            # Simplify descriptions for user guidance
            simplified = self._simplify_description(action, desc)
            
            # Only include modal info if it's a NEW modal (not repeating the same one)
            modal_info = ""
            if state.detected_modals and len(state.detected_modals) > 0:
                latest_modal = state.detected_modals[-1]
                modal_text = latest_modal.get('text', '')[:50]
                
                # Check if this modal was already mentioned in recent step descriptions
                already_mentioned = False
                if len(state.step_descriptions) > 0:
                    last_3_descriptions = state.step_descriptions[-3:]
                    for prev_desc in last_3_descriptions:
                        if modal_text and modal_text in prev_desc:
                            already_mentioned = True
                            break
                
                if not already_mentioned and modal_text:
                    # Simplify modal info
                    modal_info = f" (A popup or menu appeared)"
            
            # Check for forms
            form_info = ""
            if state.form_interactions:
                last_form = state.form_interactions[-1]
                form_info = f" (Entered information)"
            
            return f"{simplified}{modal_info}{form_info}"
        
        return f"Step {state.current_step}"
    
    def _simplify_description(self, action: str, description: str) -> str:
        """Simplify step descriptions to be more user-friendly and guide-like"""
        desc_lower = description.lower()
        
        # Common patterns to simplify
        if action == "click":
            # Extract what was clicked
            if "code" in desc_lower and "button" in desc_lower:
                return "Click the 'Code' button"
            elif "clone" in desc_lower and "url" in desc_lower:
                return "Copy the clone URL"
            elif "copy" in desc_lower and "button" in desc_lower:
                return "Click the 'Copy' button"
            elif "https" in desc_lower:
                return "Select the HTTPS option"
            elif "clone" in desc_lower:
                return "Click on the clone option"
            else:
                # Try to extract quoted text or simplify
                import re
                quoted = re.search(r'[\'"]([^\'"]+)[\'"]', description)
                if quoted:
                    return f"Click on '{quoted.group(1)}'"
                # Simplify generic click descriptions
                desc_simple = description.replace("Click", "Click on").replace("click", "Click on")
                return desc_simple[:60] if len(desc_simple) > 60 else desc_simple
        
        elif action == "wait":
            if "dropdown" in desc_lower or "menu" in desc_lower:
                return "Wait for the menu to appear"
            elif "dynamic" in desc_lower or "content" in desc_lower:
                return "Wait for the page to load"
            elif "appear" in desc_lower:
                return "Wait for the element to appear"
            else:
                return "Wait a moment"
        
        elif action == "type":
            # Extract what was typed
            import re
            text_match = re.search(r"type\s+(?:text|value|input)[\s:]*['\"]?([^'\"]+)['\"]?", desc_lower)
            if text_match:
                typed_text = text_match.group(1)[:30]
                return f"Type '{typed_text}'"
            elif "enter" in desc_lower or "text" in desc_lower:
                return "Enter text"
            else:
                return "Enter text"
        
        elif action == "select":
            return "Select an option"
        
        elif action == "hover":
            return "Hover over the element"
        
        elif action == "scroll":
            return "Scroll to view more content"
        
        # Fallback: return simplified version
        simplified = description.replace("After ", "").replace("after ", "")
        if len(simplified) > 80:
            simplified = simplified[:77] + "..."
        return simplified
    
    def _remove_duplicate_steps(self, step_descriptions: List[str]) -> List[str]:
        """Remove consecutive duplicate step descriptions"""
        if not step_descriptions:
            return []
        
        filtered = [step_descriptions[0]]  # Always keep first step
        
        for i in range(1, len(step_descriptions)):
            current = step_descriptions[i].strip()
            previous = step_descriptions[i-1].strip()
            
            # Remove common prefixes/suffixes for comparison
            current_normalized = current.lower().replace(" (a popup or menu appeared)", "").replace(" (entered information)", "").strip()
            previous_normalized = previous.lower().replace(" (a popup or menu appeared)", "").replace(" (entered information)", "").strip()
            
            # Skip if it's identical or very similar
            if current_normalized != previous_normalized:
                # Check if it's a near-duplicate using word similarity
                current_words = set(current_normalized.split())
                previous_words = set(previous_normalized.split())
                if len(current_words) > 0 and len(previous_words) > 0:
                    similarity = len(current_words & previous_words) / len(current_words | previous_words)
                    if similarity < 0.7:  # Less than 70% similar - keep it
                        filtered.append(step_descriptions[i])
                    # else skip - too similar (likely duplicate)
                else:
                    filtered.append(step_descriptions[i])
            # else skip - identical
        
        return filtered
    
    async def _save_workflow_metadata(self, state: WorkflowState):
        """Save detailed metadata about the workflow execution"""
        if not self.capture_metadata:
            return
        
        metadata = {
            "task_query": state.task_query,
            "app_name": state.app_name,
            "app_url": state.app_url,
            "task_name": state.task_name,
            "completed": state.completed,
            "error": state.error,
            "total_steps": len(state.navigation_steps),
            "steps_completed": state.current_step,
                "screenshots": state.screenshots,
            "step_descriptions": state.step_descriptions,
            "execution_time": state.execution_log[-1]["timestamp"] - state.execution_log[0]["timestamp"] if state.execution_log else 0,
            "detected_modals": len(state.detected_modals),
            "form_interactions": len(state.form_interactions),
            "ui_states_captured": len(state.ui_states),
            "execution_log": state.execution_log
        }
        
        # Save to file
        data_dir = Path(__file__).parent.parent / "data" / "screenshots" / state.app_name / state.task_name
        data_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = data_dir / "workflow_metadata.json"
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Workflow metadata saved to {metadata_path}")
    
    async def execute(
        self,
        task_query: str,
        app_url: str,
        app_name: str,
        task_name: str
    ) -> Dict[str, Any]:
        """Execute enhanced workflow with comprehensive state capture"""
        logger.log_agent_start("AgentWorkflow", task=task_query)
        
        state = WorkflowState()
        state.task_query = task_query
        state.app_url = app_url
        state.app_name = app_name
        state.task_name = task_name
        
        try:
            # Initial UI state capture
            await self._capture_ui_state(state, "initial")
            
            # Take initial screenshot
            await self._screenshot_step_enhanced(state)
            
            # Main execution loop
            while self._should_continue(state):
                await self._navigate_step_enhanced(state)
                
                # Capture screenshot after navigation step (only if step advanced)
                if state.current_step > 0 and state.current_step <= len(state.navigation_steps):
                    await self._screenshot_step_enhanced(state)
                
                # Validate state periodically
                if state.current_step % 3 == 0 and state.current_step > 0:
                    await self._validate_step(state)
                
                # Sync context
                if state.current_step > 0:
                    await self._sync_context_step(state)
            
            # Final state capture (only if different from last step)
            if state.current_step != len(state.screenshots):
                await self._capture_ui_state(state, "final")
                await self._screenshot_step_enhanced(state)
            
            # Save comprehensive metadata
            await self._save_workflow_metadata(state)
            
            # Filter out duplicate consecutive step descriptions
            filtered_descriptions = self._remove_duplicate_steps(state.step_descriptions)
            
            # Create screenshot metadata with step mappings
            screenshot_metadata = []
            for screenshot in state.screenshots:
                step_index = state.screenshot_to_step_map.get(screenshot, -1)
                screenshot_metadata.append({
                    "path": screenshot,
                    "step_index": step_index,
                    "step_number": step_index + 1 if step_index >= 0 else None
                })
            
            result = {
                "success": state.completed and not state.error,
                "screenshots": state.screenshots,
                "screenshot_metadata": screenshot_metadata,  # Include mapping info
                "step_descriptions": filtered_descriptions,
                "steps_completed": state.current_step,
                "error": state.error,
                "final_url": await self.browser.get_url(),
                "ui_states_captured": len(state.ui_states),
                "modals_detected": len(state.detected_modals),
                "forms_filled": len(state.form_interactions),
                "execution_time": time.time() - state.execution_log[0]["timestamp"] if state.execution_log else 0
            }
            
            logger.log_agent_end("AgentWorkflow", success=result["success"])
            return result
            
        except Exception as e:
            logger.log_error(e, context={"workflow": "execute"})
            logger.log_agent_end("AgentWorkflow", success=False)
            
            # Still try to save what we captured
            await self._save_workflow_metadata(state)
            
            return {
                "success": False,
                "screenshots": state.screenshots,
                "step_descriptions": state.step_descriptions,
                "error": str(e),
                "steps_completed": state.current_step
            }
    
    def _should_continue(self, state: WorkflowState) -> bool:
        """Determine if workflow should continue"""
        if state.completed or state.error:
            return False
        if state.current_step >= self.max_steps:
            logger.warning(f"Max steps ({self.max_steps}) reached")
            return False
        return True
    
    async def _validate_step(self, state: WorkflowState):
        """Validate current state"""
        try:
            validation = await self.validator.validate_state()
            state.state_valid = validation.get("valid", False)
            
            if not state.state_valid:
                issues = validation.get("issues", [])
                logger.warning(f"Validation failed: {issues}")
                self._log_execution(state, "validation_failed", {"issues": issues})
        except Exception as e:
            logger.log_error(e, context={"step": "validate"})
            state.state_valid = False
    
    async def _sync_context_step(self, state: WorkflowState):
        """Sync context with enhanced metadata"""
        try:
            workflow_id = f"{state.app_name}_{state.task_name}"
            context_data = {
                "step": state.current_step,
                "screenshots": state.screenshots,
                "state_valid": state.state_valid,
                "url": await self.browser.get_url(),
                "ui_states": len(state.ui_states),
                "modals": len(state.detected_modals),
                "forms": len(state.form_interactions)
            }
            self.context_sync.sync_context(workflow_id, state.current_step, context_data)
        except Exception as e:
            logger.log_error(e, context={"step": "sync_context"})
    
    # Backward compatibility - keep original method names
    async def _navigate_step(self, state: WorkflowState):
        """Backward compatible method that calls enhanced version"""
        return await self._navigate_step_enhanced(state)
    
    async def _screenshot_step(self, state: WorkflowState):
        """Backward compatible method that calls enhanced version"""
        return await self._screenshot_step_enhanced(state)