from typing import TypedDict, List, Dict, Any, Optional, Callable, Awaitable
from utils.logger import get_logger
from utils.browser_controller import BrowserController
from agents.ui_navigator_agent import UINavigatorAgent
from agents.screenshot_agent import ScreenshotAgent
from agents.state_validator_agent import StateValidatorAgent
from agents.context_sync_agent import ContextSyncAgent
from agents.login_agent import LoginAgent
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
        self.current_action_type: Optional[str] = None  # For screenshot agent
        self.current_action_success: bool = True  # For screenshot agent


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
        self.login_agent = LoginAgent(browser, llm_model)
    
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
                
                # Set navigation plan in screenshot agent for strategic decisions
                self.screenshot.set_navigation_plan(navigation_steps)
                
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
            
            # Validate step completion for critical actions
            step_succeeded = True
            if action_type in ["click", "type", "select"]:
                step_succeeded = await self._validate_step_completion(state, action_type, selector, description)
                if not step_succeeded:
                    logger.warning(f"Step validation failed for {action_type} on {selector}")
                    # Retry once more
                    logger.info("Retrying step...")
                    await asyncio.sleep(1)
                    try:
                        if action_type == "click":
                            await self._execute_click(state, selector, description)
                        elif action_type == "type":
                            await self._execute_type(state, selector, step.get("text", ""), description)
                        step_succeeded = await self._validate_step_completion(state, action_type, selector, description)
                    except Exception as retry_error:
                        logger.error(f"Retry also failed: {retry_error}")
                        step_succeeded = False
            
            if step_succeeded:
                self._log_execution(state, f"step_executed_{action_type}", {
                    "selector": selector,
                    "description": description,
                    "success": True
                })
                # Store action info for screenshot agent
                state.current_action_type = action_type
                state.current_action_success = True
                state.current_step += 1
            else:
                # Critical step failed - raise exception to prevent workflow from continuing
                error_msg = f"Critical step failed: {action_type} on {selector} - {description}"
                logger.error(error_msg)
                self._log_execution(state, f"step_failed_{action_type}", {
                    "selector": selector,
                    "description": description,
                    "error": "Step validation failed",
                    "success": False
                })
                # Store failed action info
                state.current_action_type = action_type
                state.current_action_success = False
                raise RuntimeError(error_msg)
            
        except Exception as e:
            logger.error(f"Error executing {action_type}: {e}")
            self._log_execution(state, f"step_failed_{action_type}", {
                "selector": selector,
                "description": description,
                "error": str(e),
                "success": False
            })
            
            # Try alternative approaches for click
            if action_type == "click" and selector:
                try:
                    await self._try_alternative_click(state, selector, description)
                    # Validate alternative click succeeded
                    if await self._validate_step_completion(state, action_type, selector, description):
                        state.current_step += 1
                        return
                except Exception as alt_error:
                    logger.error(f"Alternative click also failed: {alt_error}")
            
            # For type actions, this is critical - don't continue
            if action_type == "type":
                state.current_action_type = action_type
                state.current_action_success = False
                raise RuntimeError(f"Type action failed and is critical: {e}")
            
            # For other actions, log and continue but mark as failed
            state.current_action_type = action_type
            state.current_action_success = False
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
        """Execute type action with form interaction tracking and validation"""
        if not selector:
            raise ValueError("Empty selector for type action")
        
        if not text:
            logger.warning("No text provided for type action")
            return
        
        # Execute type action
        await self.browser.type(selector, text)
        
        # Validate that typing actually succeeded by checking if text appears in input
        try:
            # Wait a moment for value to be set
            await asyncio.sleep(0.3)
            
            # Verify the text was actually entered
            value_entered = await self.browser.page.evaluate(f"""
                (selector) => {{
                    // Try multiple selector strategies
                    const selectors = selector.split(',').map(s => s.trim());
                    for (const sel of selectors) {{
                        try {{
                            const elem = document.querySelector(sel);
                            if (elem && (elem.tagName === 'INPUT' || elem.tagName === 'TEXTAREA')) {{
                                return elem.value || elem.textContent || '';
                            }}
                        }} catch (e) {{
                            continue;
                        }}
                    }}
                    // Fallback: check all visible inputs in modals
                    const modals = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
                    for (const modal of modals) {{
                        if (modal.offsetParent !== null) {{
                            const inputs = modal.querySelectorAll('input:not([type="hidden"]), textarea');
                            for (const input of inputs) {{
                                if (input.offsetParent !== null && input.value) {{
                                    return input.value;
                                }}
                            }}
                        }}
                    }}
                    return '';
                }}
            """, selector)
            
            if value_entered and text.lower().strip() in value_entered.lower():
                logger.info(f"✓ Verified text was entered: {text[:20]}...")
            else:
                logger.warning(f"⚠ Text may not have been entered correctly. Expected: {text[:20]}, Found: {value_entered[:20] if value_entered else 'none'}")
                # Don't fail here, but log the issue
        except Exception as e:
            logger.debug(f"Could not verify text entry: {e}")
        
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
        """Execute scroll action with enhanced handling for JS-heavy sites"""
        try:
            if selector:
                # Scroll to specific element
                await self.browser.scroll_to_element(selector)
            else:
                # Scroll to bottom
                await self.browser.scroll_to_bottom()
        except Exception as e:
            logger.warning(f"Scroll action failed: {e}, trying alternative method")
            # Fallback: try direct JavaScript scroll
            try:
                if selector:
                    await self.browser.page.evaluate(f"""
                        (selector) => {{
                            const elem = document.querySelector(selector);
                            if (elem) {{
                                elem.scrollIntoView({{behavior: 'smooth', block: 'center', inline: 'center'}});
                            }}
                        }}
                    """, selector)
                else:
                    await self.browser.page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
                await asyncio.sleep(0.5)  # Wait for scroll animation
            except Exception as e2:
                logger.error(f"All scroll methods failed: {e2}")
    
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
    
    async def _validate_step_completion(self, state: WorkflowState, action_type: str, selector: str, description: str) -> bool:
        """Validate that a step actually completed successfully"""
        try:
            if action_type == "click":
                # For click, check if something changed (modal appeared, URL changed, etc.)
                await asyncio.sleep(0.5)  # Wait for effects
                
                # Check if modals appeared (common after clicks)
                modals = await self.browser.detect_and_handle_modals()
                if modals:
                    return True  # Modal appeared = click likely worked
                
                # Check if URL changed
                current_url = await self.browser.get_url()
                if current_url != state.ui_states[-1].get("url", "") if state.ui_states else "":
                    return True  # URL changed = click worked
                
                # For dropdown/menu clicks, check if menu is visible
                if "menu" in description.lower() or "dropdown" in description.lower():
                    menu_visible = await self.browser.page.evaluate("""
                        () => {
                            const menus = document.querySelectorAll('[role="menu"], [role="listbox"], .dropdown-menu, [class*="menu"]');
                            for (const menu of menus) {
                                if (menu.offsetParent !== null) {
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if menu_visible:
                        return True
                
                # If click was on a button that should open something, check if it's disabled/clicked
                return True  # Assume click worked if no errors
                
            elif action_type == "type":
                # Check if text was actually entered
                await asyncio.sleep(0.3)
                
                # Try to find the input and check its value
                value_found = await self.browser.page.evaluate(f"""
                    (selector) => {{
                        const selectors = selector.split(',').map(s => s.trim());
                        for (const sel of selectors) {{
                            try {{
                                const elem = document.querySelector(sel);
                                if (elem && (elem.tagName === 'INPUT' || elem.tagName === 'TEXTAREA')) {{
                                    return elem.value || elem.textContent || '';
                                }}
                            }} catch (e) {{
                                continue;
                            }}
                        }}
                        // Check all visible inputs in modals
                        const modals = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
                        for (const modal of modals) {{
                            if (modal.offsetParent !== null) {{
                                const inputs = modal.querySelectorAll('input:not([type="hidden"]), textarea');
                                for (const input of inputs) {{
                                    if (input.offsetParent !== null && input.value) {{
                                        return input.value;
                                    }}
                                }}
                            }}
                        }}
                        return '';
                    }}
                """, selector)
                
                # If we found a value, type likely succeeded
                return bool(value_found and len(value_found) > 0)
                
            elif action_type == "select":
                # For select, check if option was selected
                return True  # Assume success if no error
                
            return True  # Default: assume success
        except Exception as e:
            logger.debug(f"Step validation error: {e}")
            return False  # If validation fails, assume step didn't complete
    
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
        """Strategic screenshot capture using reward-based approach"""
        logger.log_action("screenshot_step_enhanced", {"step": state.current_step})
        
        try:
            # Generate context description for smart cropping
            context = await self._generate_step_description(state)
            
            # ALWAYS add step description (so all steps are visible to user)
            state.step_descriptions.append(context)
            
            # Send progress update for screenshot capture
            if self.progress_callback:
                await self.progress_callback(
                    state.current_step + 1,
                    len(state.navigation_steps) if state.navigation_steps else 0,
                    f"Evaluating screenshot: {context[:50]}",
                    "evaluating_screenshot"
                )
            
            # Use reward-based screenshot agent
            screenshot_path = await self.screenshot.capture_screenshot(
                app=state.app_name,
                task=state.task_name,
                step=state.current_step,
                context=context,
                force=False,  # Use reward-based strategy
                action_type=getattr(state, 'current_action_type', None),
                action_success=getattr(state, 'current_action_success', True)
            )
            
            # Only add screenshot path if actually captured (reward-based decision)
            if screenshot_path:
                state.screenshots.append(screenshot_path)
                # Map screenshot to the step index it corresponds to
                step_index = len(state.step_descriptions) - 1  # Current step description index
                state.screenshot_to_step_map[screenshot_path] = step_index
                self._log_execution(state, "screenshot_captured", {
                    "path": screenshot_path,
                    "description": context,
                    "action_type": getattr(state, 'current_action_type', None),
                    "action_success": getattr(state, 'current_action_success', True),
                    "step": state.current_step,
                    "step_index": step_index
                })
            else:
                # Screenshot was skipped (low reward) - but step description is already added
                logger.info(f"⏭️ Screenshot skipped at step {state.current_step} - low reward score (step still tracked)")
                self._log_execution(state, "screenshot_skipped", {
                    "reason": "low_reward",
                    "step": state.current_step,
                    "description": context,
                    "action_type": getattr(state, 'current_action_type', None)
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
            # Step 1: Check and handle authentication BEFORE navigation
            logger.info("Checking authentication requirements...")
            auth_check = await self.login_agent.check_authentication_required(app_url)
            
            if auth_check.get("requires_login", False):
                logger.info(f"Authentication required. Method: {auth_check.get('login_method', 'manual')}")
                
                # Ensure browser is in headed mode for login
                if self.browser.headless:
                    logger.warning("Login required but browser is in headless mode")
                    return {
                        "success": False,
                        "error": "Login required but browser is in headless mode. Please use headed mode for login.",
                        "requires_login": True,
                        "login_method": auth_check.get("login_method"),
                        "oauth_providers": auth_check.get("oauth_providers", [])
                    }
                
                # Handle login
                login_result = await self.login_agent.handle_login(
                    app_url=app_url,
                    login_method=auth_check.get("login_method")
                )
                
                if not login_result.get("success", False):
                    logger.error(f"Login failed: {login_result.get('message', 'Unknown error')}")
                    return {
                        "success": False,
                        "error": login_result.get("message", "Login failed"),
                        "requires_login": True,
                        "login_result": login_result
                    }
                
                logger.info("Login successful - proceeding with workflow")
            
            # Verify authentication before proceeding
            is_authenticated = await self.login_agent.verify_authentication()
            if not is_authenticated:
                logger.warning("Authentication verification failed - user may need to login")
                return {
                    "success": False,
                    "error": "Authentication verification failed",
                    "requires_login": True
                }
            
            # Initial UI state capture
            await self._capture_ui_state(state, "initial")
            
            # Take initial screenshot
            await self._screenshot_step_enhanced(state)
            
            # Main execution loop
            while self._should_continue(state):
                await self._navigate_step_enhanced(state)
                
                # Capture screenshot after navigation step (only if step actually completed)
                # Only take screenshot if step was successful (not skipped)
                if state.current_step > 0 and state.current_step <= len(state.navigation_steps):
                    # Wait a moment for UI to stabilize
                    await asyncio.sleep(0.5)
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