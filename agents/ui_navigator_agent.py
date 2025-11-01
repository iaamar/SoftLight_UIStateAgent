from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List, Tuple
from utils.logger import get_logger
from utils.browser_controller import BrowserController
import json
import re
from bs4 import BeautifulSoup

logger = get_logger(name="ui_navigator_agent")


class UINavigatorAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "gpt-4o"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Advanced UI Navigation Specialist",
            goal="Navigate complex web applications, handle dynamic content, and identify all UI states",
            backstory="""Expert in modern web UI navigation with deep knowledge of:
            - Single Page Applications (React, Vue, Angular)
            - Dynamic content loading patterns
            - Modal dialogs and popups
            - Form interactions and validation
            - Multi-step workflows
            - Authentication flows
            - Accessibility patterns (ARIA labels, roles)
            """,
            verbose=True,
            llm=self.llm
        )
    
    def _get_llm(self, model: str):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if "claude" in model.lower() or "anthropic" in model.lower():
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found")
            return ChatAnthropic(model=model, api_key=api_key)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found")
            # Remove temperature parameter entirely for compatibility
            return ChatOpenAI(model=model, api_key=api_key)
    
    async def analyze_page_structure(self) -> Dict[str, Any]:
        """Analyze the current page structure for navigation opportunities"""
        page_html = await self.browser.get_page_html()
        soup = BeautifulSoup(page_html, 'html.parser')
        
        # Find interactive elements
        buttons = soup.find_all(['button', 'a', 'input'])
        forms = soup.find_all('form')
        
        # Detect modals/dialogs
        modals = soup.find_all(['div', 'section'], attrs={
            'role': ['dialog', 'alertdialog'],
            'aria-modal': 'true'
        })
        
        # Find navigation elements
        nav_elements = soup.find_all(['nav', 'menu'])
        
        # Extract key information
        structure = {
            "interactive_elements": len(buttons),
            "forms": len(forms),
            "modals": len(modals),
            "navigation_areas": len(nav_elements),
            "has_dropdown": bool(soup.find_all(attrs={'aria-haspopup': 'true'})),
            "has_tabs": bool(soup.find_all(attrs={'role': 'tablist'})),
            "page_title": soup.title.string if soup.title else "",
            "main_headings": [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2'])[:5]]
        }
        
        return structure
    
    async def detect_workflow_type(self, task_query: str, page_structure: Dict[str, Any]) -> str:
        """Determine the type of workflow needed for the task"""
        task_lower = task_query.lower()
        
        # Common workflow patterns
        if any(word in task_lower for word in ["create", "new", "add"]):
            if "project" in task_lower:
                return "create_project"
            elif "repository" in task_lower or "repo" in task_lower:
                return "create_repository"
            elif "task" in task_lower or "issue" in task_lower:
                return "create_task"
            elif "database" in task_lower or "table" in task_lower:
                return "create_database"
            else:
                return "create_generic"
        
        elif any(word in task_lower for word in ["filter", "search", "find"]):
            return "filter_search"
        
        elif any(word in task_lower for word in ["settings", "preferences", "configure"]):
            return "settings_navigation"
        
        elif any(word in task_lower for word in ["edit", "update", "modify"]):
            return "edit_workflow"
        
        elif any(word in task_lower for word in ["delete", "remove"]):
            return "delete_workflow"
        
        else:
            return "generic_navigation"
    
    async def generate_smart_navigation_steps(
        self, 
        task_query: str, 
        workflow_type: str,
        page_html: str,
        current_url: str
    ) -> List[Dict[str, Any]]:
        """Generate navigation steps based on workflow type and page analysis"""
        
        # Prepare context-aware prompt
        workflow_prompts = {
            "create_project": """
            For creating a project, typical steps include:
            1. Click 'New Project' or '+' button
            2. Fill in project name
            3. Select project type/template if available
            4. Configure project settings
            5. Click 'Create' or 'Save'
            """,
            "create_repository": """
            For creating a repository, typical steps include:
            1. Click 'New' or 'New repository' button
            2. Enter repository name
            3. Add description (optional)
            4. Choose visibility (public/private)
            5. Initialize with README if option exists
            6. Click 'Create repository'
            """,
            "filter_search": """
            For filtering/searching, typical steps include:
            1. Locate filter button or search box
            2. Click filter options or enter search terms
            3. Select filter criteria
            4. Apply filters
            5. Verify filtered results
            """,
            "settings_navigation": """
            For settings navigation:
            1. Click user avatar/menu
            2. Select 'Settings' or 'Preferences'
            3. Navigate to specific settings section
            4. Make configuration changes
            5. Save changes
            """
        }
        
        workflow_hint = workflow_prompts.get(workflow_type, "")
        
        # Use the task to generate navigation plan
        task_description = f"""
        Task: {task_query}
        Current URL: {current_url}
        Workflow Type: {workflow_type}
        
        {workflow_hint}
        
        IMPORTANT INSTRUCTIONS:
        1. Analyze the HTML to find EXACT selectors that exist on the page
        2. Use specific selectors in this priority order:
           - ID selectors: #element-id
           - Data attributes: [data-testid="..."], [data-test="..."]
           - ARIA labels: [aria-label="..."]
           - Button/link text: button:has-text('...'), a:has-text('...')
           - Class names (only if unique): .unique-class
        
        3. For dynamic content:
           - Add wait steps after clicks that might trigger loading
           - Look for spinner/loader elements
           - Consider modals that might appear
        
        4. For form fields:
           - Use name, id, or placeholder attributes
           - Include realistic sample data
        
        Page HTML Analysis (first 15000 chars):
        {page_html[:15000]}
        
        Generate a JSON array of navigation steps. Each step must have:
        - action_type: "click", "type", "wait", "select", "hover", "scroll"
        - selector: Valid CSS/Playwright selector that exists in the HTML
        - description: Human-readable description
        - text: (for type actions) Text to enter
        - wait_time: (for wait actions) Seconds to wait
        - options: (for select actions) Option to select
        
        RETURN ONLY VALID JSON ARRAY!
        """
        
        # Create and execute the task
        task = Task(
            description=task_description,
            expected_output="A JSON array of navigation steps with exact selectors from the HTML",
            agent=self.agent
        )
        
        crew = Crew(agents=[self.agent], tasks=[task])
        result = crew.kickoff()
        
        # Parse the result
        steps = self._parse_enhanced_navigation_plan(str(result))
        return steps
    
    def _parse_enhanced_navigation_plan(self, plan_text: str) -> List[Dict[str, Any]]:
        """Enhanced parser for navigation plans with better error handling"""
        logger.debug(f"Parsing navigation plan, length: {len(plan_text)} chars")
        
        # Multiple strategies to extract JSON
        strategies = [
            # Strategy 1: Look for markdown code blocks
            lambda: re.search(r'```(?:json)?\s*(\[.*?\])\s*```', plan_text, re.DOTALL),
            # Strategy 2: Find array with balanced brackets
            lambda: self._extract_json_array(plan_text),
            # Strategy 3: Find individual JSON objects
            lambda: self._extract_json_objects(plan_text)
        ]
        
        for strategy in strategies:
            try:
                result = strategy()
                if result:
                    if isinstance(result, re.Match):
                        json_str = result.group(1)
                    else:
                        json_str = result
                    
                    parsed = json.loads(json_str) if isinstance(json_str, str) else json_str
                    if isinstance(parsed, list) and len(parsed) > 0:
                        logger.info(f"Successfully parsed {len(parsed)} navigation steps")
                        return self._validate_navigation_steps(parsed)
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue
        
        # Fallback: Generate basic steps based on common patterns
        logger.warning("Failed to parse LLM response, generating fallback steps")
        return self._generate_fallback_steps(plan_text)
    
    def _extract_json_array(self, text: str) -> Optional[str]:
        """Extract JSON array with proper bracket matching"""
        bracket_count = 0
        start_idx = -1
        in_string = False
        escape_next = False
        
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
                
            if char == '\\':
                escape_next = True
                continue
                
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '[':
                    if bracket_count == 0:
                        start_idx = i
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0 and start_idx != -1:
                        return text[start_idx:i+1]
        
        return None
    
    def _extract_json_objects(self, text: str) -> Optional[List[Dict]]:
        """Extract individual JSON objects and return as list"""
        objects = []
        brace_count = 0
        start_idx = -1
        in_string = False
        escape_next = False
        
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
                
            if char == '\\':
                escape_next = True
                continue
                
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '{':
                    if brace_count == 0:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx != -1:
                        try:
                            obj_str = text[start_idx:i+1]
                            obj = json.loads(obj_str)
                            if self._is_valid_navigation_step(obj):
                                objects.append(obj)
                        except:
                            pass
                        start_idx = -1
        
        return objects if objects else None
    
    def _is_valid_navigation_step(self, obj: Dict) -> bool:
        """Check if object is a valid navigation step"""
        required_fields = ["action_type", "selector", "description"]
        return all(field in obj for field in required_fields)
    
    def _validate_navigation_steps(self, steps: List[Dict]) -> List[Dict]:
        """Validate and enhance navigation steps"""
        validated_steps = []
        
        for step in steps:
            # Ensure required fields
            if not self._is_valid_navigation_step(step):
                continue
            
            # Enhance step with defaults
            enhanced_step = {
                "action_type": step.get("action_type", "click").lower(),
                "selector": step.get("selector", "").strip(),
                "description": step.get("description", ""),
                "text": step.get("text", ""),
                "wait_time": step.get("wait_time", 2),
                "options": step.get("options", "")
            }
            
            # Skip invalid selectors
            if not enhanced_step["selector"] and enhanced_step["action_type"] != "wait":
                continue
            
            validated_steps.append(enhanced_step)
        
        return validated_steps
    
    def _generate_fallback_steps(self, text: str) -> List[Dict]:
        """Generate basic navigation steps from text analysis"""
        steps = []
        
        # Look for action keywords in the text
        action_patterns = [
            (r"click[s]?\s+(?:on\s+)?(?:the\s+)?['\"]([^'\"]+)['\"]", "click"),
            (r"type[s]?\s+['\"]([^'\"]+)['\"]", "type"),
            (r"select[s]?\s+['\"]([^'\"]+)['\"]", "select"),
            (r"wait[s]?\s+(?:for\s+)?(\d+)", "wait")
        ]
        
        for pattern, action_type in action_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if action_type == "wait":
                    steps.append({
                        "action_type": "wait",
                        "wait_time": int(match.group(1)),
                        "selector": "",
                        "description": f"Wait for {match.group(1)} seconds"
                    })
                else:
                    steps.append({
                        "action_type": action_type,
                        "selector": match.group(1),
                        "description": f"{action_type.capitalize()} {match.group(1)}"
                    })
        
        return steps
    
    async def navigate_to_task(self, task_query: str, app_url: str) -> List[Dict[str, Any]]:
        """Main navigation method with enhanced capabilities"""
        logger.log_agent_start("UINavigatorAgent", task=task_query)
        
        try:
            # Navigate to the app
            await self.browser.navigate(app_url)
            await self.browser.wait_for_stable_page()
            
            # Analyze page structure
            page_structure = await self.analyze_page_structure()
            logger.info(f"Page structure: {page_structure}")
            
            # Detect workflow type
            workflow_type = await self.detect_workflow_type(task_query, page_structure)
            logger.info(f"Detected workflow type: {workflow_type}")
            
            # Get current state
            current_url = await self.browser.get_url()
            page_html = await self.browser.get_page_html()
            
            # Check for modals that might be blocking
            modals = await self.browser.detect_and_handle_modals()
            if modals:
                logger.info(f"Detected {len(modals)} modals on page")
            
            # Generate navigation steps
            steps = await self.generate_smart_navigation_steps(
                task_query=task_query,
                workflow_type=workflow_type,
                page_html=page_html,
                current_url=current_url
            )
            
            # Enhance steps with dynamic content handling
            enhanced_steps = await self._enhance_steps_for_dynamic_content(steps)
            
            logger.log_agent_end("UINavigatorAgent", success=True)
            logger.info(f"Generated {len(enhanced_steps)} enhanced navigation steps")
            
            return enhanced_steps
            
        except Exception as e:
            logger.log_error(e, context={"agent": "UINavigatorAgent"})
            logger.log_agent_end("UINavigatorAgent", success=False)
            raise
    
    async def _enhance_steps_for_dynamic_content(self, steps: List[Dict]) -> List[Dict]:
        """Add wait steps and handle dynamic content"""
        enhanced_steps = []
        
        for i, step in enumerate(steps):
            enhanced_steps.append(step)
            
            # Add wait after actions that typically trigger dynamic content
            if step["action_type"] == "click":
                # Check if this might open a modal or load content
                description_lower = step["description"].lower()
                if any(word in description_lower for word in ["new", "create", "add", "open", "show", "filter"]):
                    enhanced_steps.append({
                        "action_type": "wait",
                        "wait_time": 2,
                        "selector": "",
                        "description": "Wait for dynamic content to load"
                    })
        
        return enhanced_steps
    
    # Backward compatibility - keep original method name
    def _parse_navigation_plan(self, plan_text: str) -> List[Dict[str, Any]]:
        """Backward compatible method that calls the enhanced parser"""
        return self._parse_enhanced_navigation_plan(plan_text)