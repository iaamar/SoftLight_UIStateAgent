"""
Selenium fallback support for when Playwright fails on JavaScript-heavy sites.
This module provides a fallback mechanism using Selenium WebDriver.
"""
import os
from typing import Optional, Dict, Any
from utils.logger import get_logger

logger = get_logger(name="selenium_fallback")

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logger.warning("Selenium not available - fallback will not work. Install with: pip install selenium")


class SeleniumFallback:
    """Selenium fallback for when Playwright fails"""
    
    def __init__(self, headless: bool = True):
        self.driver: Optional[webdriver.Chrome] = None
        self.headless = headless
        self.available = SELENIUM_AVAILABLE
    
    def is_available(self) -> bool:
        """Check if Selenium is available"""
        return self.available
    
    def start(self, url: Optional[str] = None):
        """Start Selenium WebDriver"""
        if not self.available:
            raise RuntimeError("Selenium is not available")
        
        try:
            options = ChromeOptions()
            if self.headless:
                options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--window-size=1920,1080')
            
            # Try to use existing Chrome installation
            try:
                self.driver = webdriver.Chrome(options=options)
            except Exception:
                # Try with service
                service = ChromeService()
                self.driver = webdriver.Chrome(service=service, options=options)
            
            if url:
                self.driver.get(url)
            
            logger.info("Selenium WebDriver started successfully")
        except Exception as e:
            logger.error(f"Failed to start Selenium: {e}")
            raise
    
    def click(self, selector: str, timeout: int = 10) -> bool:
        """Click an element using Selenium"""
        if not self.driver:
            raise RuntimeError("Selenium driver not started")
        
        try:
            # Wait for element to be clickable
            wait = WebDriverWait(self.driver, timeout)
            
            # Try multiple selector strategies
            element = None
            strategies = [
                (By.CSS_SELECTOR, selector),
                (By.XPATH, f"//*[@id='{selector}']" if selector.startswith('#') else None),
                (By.XPATH, f"//button[contains(text(), '{selector}')]"),
                (By.XPATH, f"//a[contains(text(), '{selector}')]"),
            ]
            
            for by, value in strategies:
                if not value:
                    continue
                try:
                    element = wait.until(EC.element_to_be_clickable((by, value)))
                    break
                except TimeoutException:
                    continue
            
            if not element:
                raise NoSuchElementException(f"Element not found: {selector}")
            
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            
            # Try multiple click methods
            try:
                element.click()
            except Exception:
                # Fallback: JavaScript click
                self.driver.execute_script("arguments[0].click();", element)
            
            logger.info(f"✓ Selenium click succeeded: {selector}")
            return True
        except Exception as e:
            logger.error(f"Selenium click failed: {e}")
            return False
    
    def type(self, selector: str, text: str, clear_first: bool = True) -> bool:
        """Type text into an element using Selenium"""
        if not self.driver:
            raise RuntimeError("Selenium driver not started")
        
        try:
            wait = WebDriverWait(self.driver, 10)
            element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            
            # Focus and clear if needed
            element.click()
            if clear_first:
                element.clear()
            
            # Type character by character (some sites need this)
            for char in text:
                element.send_keys(char)
            
            # Trigger input events
            self.driver.execute_script("""
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, element)
            
            logger.info(f"✓ Selenium type succeeded: {selector}")
            return True
        except Exception as e:
            logger.error(f"Selenium type failed: {e}")
            return False
    
    def scroll_to_element(self, selector: str) -> bool:
        """Scroll to an element using Selenium"""
        if not self.driver:
            raise RuntimeError("Selenium driver not started")
        
        try:
            element = self.driver.find_element(By.CSS_SELECTOR, selector)
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            logger.info(f"✓ Selenium scroll succeeded: {selector}")
            return True
        except Exception as e:
            logger.error(f"Selenium scroll failed: {e}")
            return False
    
    def get_url(self) -> str:
        """Get current URL"""
        if not self.driver:
            return ""
        return self.driver.current_url
    
    def close(self):
        """Close Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

