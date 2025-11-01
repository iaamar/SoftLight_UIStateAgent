# Robust Playwright Implementation Guide

## Overview

This guide demonstrates how the enhanced SoftLight UI State Agent implements robust Playwright automation to handle the requirements specified in the engineering take-home assignment. The system can reliably capture UI states including those without URLs (modals, dropdowns, dynamic content) across modern web applications.

## Key Implementation Features

### 1. Enhanced Browser Controller

The `BrowserControllerEnhanced` class provides production-ready browser automation:

```python
from utils.browser_controller_enhanced import BrowserControllerEnhanced

# Initialize with robust configuration
browser = BrowserControllerEnhanced(
    headless=True,                    # Can run headlessly or with UI
    browser_type="chromium",          # Supports chromium, firefox, webkit
    timeout=30000,                    # Generous timeout for slow operations
    viewport_width=1920,              # Full HD viewport
    viewport_height=1080,
    context_state_file="session.json" # Persist authentication
)
```

### 2. Robust Error Handling

#### Retry Decorator
```python
@retry_on_error(max_attempts=3, delay=1.0)
async def navigate(self, url: str, wait_until: str = "domcontentloaded"):
    # Automatically retries failed operations
```

#### Multiple Navigation Strategies
- First tries `domcontentloaded` (fastest)
- Falls back to `networkidle` (most thorough)
- Final fallback to basic load

### 3. Dynamic Content Handling

#### Page Stability Detection
```python
async def wait_for_stable_page(self, stability_time: float = 0.5, max_wait: float = 5.0):
    # Monitors both DOM changes and network activity
    # Only proceeds when page is truly stable
```

This ensures we capture states after:
- AJAX requests complete
- Animations finish
- Dynamic content loads

### 4. Advanced Element Detection

#### Multi-Strategy Selector Finding
```python
async def find_element_by_text(self, text: str, element_type: str = "button"):
    # Tries multiple strategies:
    # 1. Exact text match
    # 2. Partial text match
    # 3. ARIA labels
    # 4. Title attributes
    # 5. Case variations
    # 6. Data attributes
```

#### Alternative Selector Generation
When primary selectors fail, the system automatically finds alternatives:
- ID selectors (most reliable)
- Data attributes (framework-specific)
- Class names (if unique)
- Text content (last resort)

### 5. Modal and Popup Detection

```python
async def detect_and_handle_modals(self) -> List[Dict[str, Any]]:
    # Detects modals by:
    # - ARIA roles (dialog, alertdialog)
    # - CSS classes (modal, popup, overlay)
    # - Positioning and visibility
```

This captures UI states that don't have URLs, such as:
- Create dialogs
- Confirmation popups
- Settings modals
- Form overlays

### 6. Comprehensive State Capture

```python
async def capture_full_workflow_state(self) -> Dict[str, Any]:
    # Captures:
    # - URL and title
    # - Viewport information
    # - Cookies and storage
    # - Active modals
    # - Form states
    # - Navigation history
```

### 7. Smart Navigation Planning

The `UINavigatorAgentEnhanced` analyzes tasks and generates appropriate steps:

```python
# Workflow detection
workflow_type = await self.detect_workflow_type(task_query, page_structure)

# Generates context-aware steps
if workflow_type == "create_project":
    # Knows to look for "New Project" buttons
    # Expects modal dialogs
    # Plans for form filling
```

### 8. Session Persistence

Authentication is preserved across runs:

```python
# Sessions stored per application
context_state_file = f"data/sessions/{app_name}_session.json"

# Automatic session recovery on subsequent runs
if os.path.exists(context_state_file):
    # Restores cookies, localStorage, auth tokens
```

## Handling Specific Requirements

### 1. Capturing Non-URL States

**Problem**: Modals and dropdowns don't have unique URLs

**Solution**:
```python
# Pre-click state capture
await self._capture_ui_state(state, "pre_click_new_project")

# Click action
await browser.click("button:has-text('New Project')")

# Wait for modal
await browser.wait_for_stable_page()
modals = await browser.detect_and_handle_modals()

# Post-click state capture
await self._capture_ui_state(state, "post_click_modal_open")

# Screenshot with modal highlighted
await browser.smart_screenshot(
    app="linear",
    task="create_project",
    step=1,
    highlight_elements=[".modal-container"]
)
```

### 2. Handling Dynamic SPAs

**Problem**: React/Vue/Angular apps load content dynamically

**Solution**:
```python
# Smart waiting strategies
await browser.wait_for_stable_page()  # Waits for DOM/network stability

# Alternative: Wait for specific elements
await browser.wait_for_element(".project-form", state="visible")

# Monitor for changes during wait
while time.time() - start < timeout:
    modals = await browser.detect_and_handle_modals()
    if new_modal_appeared:
        break
```

### 3. Form Interaction Tracking

**Problem**: Need to capture form states and validation

**Solution**:
```python
# Intelligent form filling
await browser.handle_form_fields({
    "project_name": "My New Project",
    "description": "Test project description",
    "visibility": "private"
})

# Tracks what was filled
state.form_interactions.append({
    "field": "project_name",
    "value": "My New Project",
    "timestamp": time.time()
})
```

### 4. Error Recovery

**Problem**: Elements might not be immediately available or clickable

**Solution**:
```python
# Primary click attempt
try:
    await browser.click(selector, retry=True)
except:
    # Try alternative methods:
    # 1. Find by text
    alt_selector = await browser.find_element_by_text("Create Project")
    
    # 2. JavaScript click
    await browser.page.evaluate(f"document.querySelector('{selector}').click()")
    
    # 3. Wait and retry
    await browser.wait_for_element_clickable(selector)
```

## Real-World Examples

### 1. Linear - Creating a Project

```python
# Task: "How do I create a project in Linear?"

# Step 1: Initial page
screenshot: "linear/create_project/step_000.png"
description: "Initial Linear workspace view"

# Step 2: Click New Project (no URL change)
screenshot: "linear/create_project/step_001.png"  
description: "After clicking New Project - modal open"
ui_state: {
    "modals": [{"type": "create_project", "fields": ["name", "identifier", "icon"]}],
    "url": "https://linear.app/workspace/projects"  # Same URL!
}

# Step 3: Fill form
screenshot: "linear/create_project/step_002.png"
description: "Project form filled"

# Step 4: Submit
screenshot: "linear/create_project/step_003.png"
description: "Project created successfully"
```

### 2. Notion - Creating a Database

```python
# Handles Notion's complex UI:
# - Slash commands
# - Inline creation
# - Dynamic menus
# - Property configuration
```

### 3. Asana - Setting up Automation

```python
# Captures workflow automation setup:
# - Rule triggers
# - Action configuration  
# - Condition builders
# All without URL changes
```

## Best Practices

### 1. Task Query Format
```
✅ Good: "How do I create a new project in Linear?"
✅ Good: "How do I filter issues by status in Notion?"
❌ Bad: "Linear project"
❌ Bad: "Create"
```

### 2. Handling Authentication
```python
# First run - login required
{
    "requires_login": true,
    "oauth_providers": ["google", "github"],
    "login_url": "https://linear.app/login"
}

# Subsequent runs - session restored automatically
```

### 3. Debugging Failed Workflows
```python
# Check workflow metadata
cat data/screenshots/linear/create_project/workflow_metadata.json

# Review execution log
"execution_log": [
    {"event": "navigation", "url": "...", "success": true},
    {"event": "click_failed", "selector": "...", "error": "..."},
    {"event": "alternative_selector_found", "selector": "..."}
]
```

## Performance Optimizations

### 1. Parallel Operations
- Concurrent modal and form detection
- Batch element queries
- Async screenshot capture

### 2. Smart Caching
- Session persistence reduces login overhead
- Selector caching for repeated elements
- State deduplication

### 3. Resource Management
- Automatic browser cleanup
- Memory-efficient HTML parsing
- Configurable timeouts

## Integration with the API

### Basic Usage
```bash
curl -X POST http://localhost:8000/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_query": "How do I create a project in Linear?",
    "app_url": "https://linear.app",
    "app_name": "linear",
    "capture_metadata": true
  }'
```

### Response
```json
{
    "success": true,
    "screenshots": [
        "linear/create_project/step_000.png",
        "linear/create_project/step_001.png",
        "linear/create_project/step_002.png"
    ],
    "step_descriptions": [
        "Initial workspace view",
        "New Project modal open",
        "Project created successfully"
    ],
    "ui_states_captured": 4,
    "modals_detected": 1,
    "forms_filled": 1,
    "execution_time": 15.3
}
```

## Troubleshooting

### Common Issues and Solutions

1. **Element not found**
   - Check if element is in iframe
   - Verify element is visible
   - Try alternative selectors

2. **Timeout errors**
   - Increase timeout in config
   - Check network conditions
   - Verify page is loading

3. **Modal not detected**
   - Add custom modal selectors
   - Check z-index and visibility
   - Ensure proper wait time

4. **Form filling fails**
   - Verify field selectors
   - Check for dynamic validation
   - Handle field dependencies

## Conclusion

This enhanced implementation provides a robust solution for capturing UI states across modern web applications. It handles:

- ✅ Non-URL states (modals, popups)
- ✅ Dynamic content loading
- ✅ Complex SPAs
- ✅ Authentication flows
- ✅ Error recovery
- ✅ Form interactions
- ✅ Multi-step workflows

The system is production-ready and can be extended for additional applications and use cases.
