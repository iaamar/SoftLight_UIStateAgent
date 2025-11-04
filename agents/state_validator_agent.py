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
                Validate the current UI state:
                Current URL: {current_url}
                Page content preview: {page_text[:500]}
                Expected state: {expected_state or 'No specific expectation'}
                
                Check:
                1. Is the page loaded completely?
                2. Are there any error messages visible?
                3. Is the expected UI element present?
                4. Is the state valid for proceeding?
                
                Return validation result with:
                - valid: boolean
                - issues: list of any issues found
                - ready_to_proceed: boolean
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
