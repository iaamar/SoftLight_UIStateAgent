from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from utils.browser_controller import BrowserController

logger = get_logger(name="state_validator_agent")


class StateValidatorAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="UI State Validation Specialist",
            goal="Validate that UI states are complete and valid at each step",
            backstory="Expert in verifying UI completeness, error detection, and state validation",
            verbose=True,
            llm=self.llm
        )
    
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
            # Remove temperature parameter entirely for compatibility
            return ChatOpenAI(model=model, api_key=api_key)
    
    async def validate_state(self, expected_state: Optional[str] = None) -> Dict[str, Any]:
        logger.log_agent_start("StateValidatorAgent")
        
        try:
            current_url = await self.browser.get_url()
            page_text = await self.browser.get_text("body")
            
            task = Task(
                description=f"""
You are an expert UI state validator. Your goal is to thoroughly validate the current UI state and determine if it's safe to proceed with the next navigation step.

**Current State Information**:
- Current URL: {current_url}
- Page content preview: {page_text[:500]}
- Expected state: {expected_state or 'No specific expectation'}

**Validation Checklist** (be thorough):
1. **Page Load Status**: 
   - Is the page fully loaded? (not showing loading spinners, placeholders, or skeleton screens)
   - Are there any network errors or failed requests?
   - Is the DOM stable (not rapidly changing)?

2. **Error Detection**:
   - Are there any visible error messages, alerts, or warnings?
   - Check for common error patterns: "Error", "Failed", "Not found", "Unauthorized", "403", "404", "500"
   - Are there form validation errors?
   - Any JavaScript console errors that might affect functionality?

3. **Expected Element Presence**:
   - If an expected state is provided, verify that the expected UI elements are present
   - Are interactive elements (buttons, forms, links) visible and accessible?
   - Are there any blocking overlays, modals, or popups that need to be handled?

4. **State Stability**:
   - Is the page in a stable state (not actively loading content)?
   - Are there any pending animations or transitions?
   - Is the UI responsive and ready for user interaction?

5. **Navigation Readiness**:
   - Can the user proceed with the next step in the workflow?
   - Are there any blockers preventing progression?
   - Is the current state appropriate for the expected action?

**Important**: Be specific about any issues found. If there are problems, describe them clearly so they can be addressed.

Return validation result as JSON with:
- valid: boolean (true if state is valid and ready to proceed)
- issues: list of strings describing any problems found (empty if no issues)
- ready_to_proceed: boolean (true if it's safe to continue navigation)
- state_type: string (e.g., "url_state", "modal_state", "form_state", "loading_state")
                """,
                expected_output="A JSON object with valid (boolean), issues (list), and ready_to_proceed (boolean) fields indicating the validation result.",
                agent=self.agent
            )
            
            crew = Crew(agents=[self.agent], tasks=[task])
            result = crew.kickoff()
            
            validation_result = self._parse_validation(str(result))
            logger.log_agent_end("StateValidatorAgent", success=validation_result.get('valid', False))
            return validation_result
        except Exception as e:
            logger.log_error(e, context={"agent": "StateValidatorAgent"})
            logger.log_agent_end("StateValidatorAgent", success=False)
            return {"valid": False, "issues": [str(e)], "ready_to_proceed": False}
    
    def _parse_validation(self, validation_text: str) -> Dict[str, Any]:
        import json
        import re
        
        json_match = re.search(r'\{.*\}', validation_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        valid = 'valid' in validation_text.lower() and 'true' in validation_text.lower()
        ready = 'ready' in validation_text.lower() and 'proceed' in validation_text.lower()
        
        return {
            "valid": valid,
            "issues": [] if valid else ["Validation unclear"],
            "ready_to_proceed": ready
        }
