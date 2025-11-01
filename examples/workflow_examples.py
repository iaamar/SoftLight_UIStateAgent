"""
Example workflows for testing the enhanced UI State Capture system
These examples demonstrate various task types across different applications
"""

# Linear Examples
LINEAR_WORKFLOWS = [
    {
        "app_name": "linear",
        "app_url": "https://linear.app",
        "workflows": [
            {
                "task_query": "How do I create a new project in Linear?",
                "task_name": "create_new_project",
                "expected_steps": [
                    "Click on workspace menu or projects section",
                    "Click 'New Project' or '+' button",
                    "Fill in project name",
                    "Select project icon (optional)",
                    "Choose project lead (optional)",
                    "Click 'Create project' button"
                ]
            },
            {
                "task_query": "How do I create a new issue in Linear?",
                "task_name": "create_new_issue",
                "expected_steps": [
                    "Click 'New Issue' button or press 'C'",
                    "Enter issue title",
                    "Add description (optional)",
                    "Set priority",
                    "Assign to team member",
                    "Add labels",
                    "Create issue"
                ]
            },
            {
                "task_query": "How do I filter issues by status in Linear?",
                "task_name": "filter_issues_by_status",
                "expected_steps": [
                    "Navigate to issues view",
                    "Click on filter button",
                    "Select 'Status' filter",
                    "Choose status options (Todo, In Progress, Done)",
                    "Apply filters"
                ]
            },
            {
                "task_query": "How do I create a new team in Linear?",
                "task_name": "create_new_team",
                "expected_steps": [
                    "Go to Settings",
                    "Navigate to Teams section",
                    "Click 'New Team'",
                    "Enter team name",
                    "Set team identifier",
                    "Configure team settings",
                    "Create team"
                ]
            },
            {
                "task_query": "How do I set up a project roadmap in Linear?",
                "task_name": "setup_roadmap",
                "expected_steps": [
                    "Navigate to Roadmap view",
                    "Click 'New Roadmap' or configure existing",
                    "Add projects to roadmap",
                    "Set timeline view",
                    "Configure milestones"
                ]
            }
        ]
    }
]

# Notion Examples
NOTION_WORKFLOWS = [
    {
        "app_name": "notion",
        "app_url": "https://www.notion.so",
        "workflows": [
            {
                "task_query": "How do I create a new workspace in Notion?",
                "task_name": "create_workspace",
                "expected_steps": [
                    "Click on workspace switcher",
                    "Select 'Create or join workspace'",
                    "Choose 'Create new workspace'",
                    "Enter workspace name",
                    "Configure workspace settings",
                    "Invite team members (optional)"
                ]
            },
            {
                "task_query": "How do I create a database in Notion?",
                "task_name": "create_database",
                "expected_steps": [
                    "Click '+' or 'Add a page'",
                    "Select 'Database'",
                    "Choose database type (Table, Board, Calendar, etc.)",
                    "Name the database",
                    "Add properties/columns",
                    "Configure property types"
                ]
            },
            {
                "task_query": "How do I create a project template in Notion?",
                "task_name": "create_project_template",
                "expected_steps": [
                    "Create new page",
                    "Add title 'Project Template'",
                    "Add sections (Overview, Tasks, Timeline)",
                    "Insert database for tasks",
                    "Add properties",
                    "Save as template"
                ]
            },
            {
                "task_query": "How do I filter a database view in Notion?",
                "task_name": "filter_database",
                "expected_steps": [
                    "Open database",
                    "Click 'Filter' button",
                    "Add filter condition",
                    "Select property to filter by",
                    "Choose filter operator",
                    "Enter filter value",
                    "Apply filter"
                ]
            },
            {
                "task_query": "How do I share a page in Notion?",
                "task_name": "share_page",
                "expected_steps": [
                    "Open page to share",
                    "Click 'Share' button",
                    "Toggle 'Share to web' or add people",
                    "Set permissions",
                    "Copy link or send invites"
                ]
            }
        ]
    }
]

# Asana Examples
ASANA_WORKFLOWS = [
    {
        "app_name": "asana",
        "app_url": "https://app.asana.com",
        "workflows": [
            {
                "task_query": "How do I create a new project in Asana?",
                "task_name": "create_project",
                "expected_steps": [
                    "Click '+' button in sidebar",
                    "Select 'Project'",
                    "Choose 'Blank project' or template",
                    "Enter project name",
                    "Select team",
                    "Choose layout (List, Board, Timeline)",
                    "Set privacy settings",
                    "Create project"
                ]
            },
            {
                "task_query": "How do I create a task in Asana?",
                "task_name": "create_task",
                "expected_steps": [
                    "Click 'Add Task' or '+' in a project",
                    "Enter task name",
                    "Add description",
                    "Set assignee",
                    "Add due date",
                    "Add to project(s)",
                    "Add tags",
                    "Create task"
                ]
            },
            {
                "task_query": "How do I set up a workflow automation in Asana?",
                "task_name": "setup_automation",
                "expected_steps": [
                    "Navigate to project",
                    "Click 'Customize' menu",
                    "Select 'Rules'",
                    "Click 'Add Rule'",
                    "Choose trigger condition",
                    "Select action to perform",
                    "Configure rule details",
                    "Activate rule"
                ]
            },
            {
                "task_query": "How do I create a portfolio in Asana?",
                "task_name": "create_portfolio",
                "expected_steps": [
                    "Click 'Portfolios' in sidebar",
                    "Click 'New Portfolio'",
                    "Enter portfolio name",
                    "Add projects to portfolio",
                    "Set up custom fields",
                    "Configure status updates"
                ]
            },
            {
                "task_query": "How do I create a form in Asana?",
                "task_name": "create_form",
                "expected_steps": [
                    "Open project",
                    "Click 'Customize'",
                    "Select 'Forms'",
                    "Click 'Add form'",
                    "Add form fields",
                    "Map fields to task properties",
                    "Configure form settings",
                    "Publish form"
                ]
            }
        ]
    }
]

# Additional Examples for other apps
GITHUB_WORKFLOWS = [
    {
        "app_name": "github",
        "app_url": "https://github.com",
        "workflows": [
            {
                "task_query": "How do I create a new repository on GitHub?",
                "task_name": "create_repository",
                "expected_steps": [
                    "Click '+' icon in header",
                    "Select 'New repository'",
                    "Enter repository name",
                    "Add description",
                    "Choose visibility (public/private)",
                    "Initialize with README",
                    "Select .gitignore template",
                    "Choose license",
                    "Create repository"
                ]
            }
        ]
    }
]

# Test Execution Helper
def get_test_workflows(app_name: str = None):
    """Get test workflows for a specific app or all apps"""
    all_workflows = {
        "linear": LINEAR_WORKFLOWS[0]["workflows"],
        "notion": NOTION_WORKFLOWS[0]["workflows"],
        "asana": ASANA_WORKFLOWS[0]["workflows"],
        "github": GITHUB_WORKFLOWS[0]["workflows"]
    }
    
    if app_name:
        return all_workflows.get(app_name, [])
    return all_workflows


# Example usage function
async def run_workflow_examples(api_base_url: str = "http://localhost:8000"):
    """Run example workflows against the API"""
    import aiohttp
    import asyncio
    
    async with aiohttp.ClientSession() as session:
        # Test Linear workflows
        for workflow in LINEAR_WORKFLOWS[0]["workflows"]:
            print(f"\nTesting: {workflow['task_query']}")
            
            payload = {
                "task_query": workflow["task_query"],
                "app_url": LINEAR_WORKFLOWS[0]["app_url"],
                "app_name": LINEAR_WORKFLOWS[0]["app_name"],
                "task_name": workflow["task_name"]
            }
            
            try:
                async with session.post(f"{api_base_url}/api/v1/execute", json=payload) as response:
                    result = await response.json()
                    
                    if result.get("requires_login"):
                        print(f"  ❗ Login required for {LINEAR_WORKFLOWS[0]['app_name']}")
                        print(f"  OAuth providers: {result.get('oauth_providers', [])}")
                    elif result.get("success"):
                        print(f"  ✅ Success! Captured {len(result.get('screenshots', []))} screenshots")
                        print(f"  UI states: {result.get('ui_states_captured', 0)}")
                        print(f"  Modals detected: {result.get('modals_detected', 0)}")
                        print(f"  Forms filled: {result.get('forms_filled', 0)}")
                        print(f"  Execution time: {result.get('execution_time', 0):.2f}s")
                    else:
                        print(f"  ❌ Failed: {result.get('error', 'Unknown error')}")
                        
            except Exception as e:
                print(f"  ❌ Error calling API: {str(e)}")
            
            # Small delay between workflows
            await asyncio.sleep(2)


# Workflow validation helper
def validate_captured_workflow(captured_screenshots: list, expected_steps: list):
    """Validate that captured screenshots match expected workflow steps"""
    print("\nWorkflow Validation:")
    print(f"Expected steps: {len(expected_steps)}")
    print(f"Captured screenshots: {len(captured_screenshots)}")
    
    if len(captured_screenshots) < len(expected_steps):
        print("⚠️  Warning: Fewer screenshots than expected steps")
    elif len(captured_screenshots) > len(expected_steps):
        print("ℹ️  Info: More screenshots than expected (may include intermediate states)")
    
    for i, (screenshot, expected) in enumerate(zip(captured_screenshots, expected_steps)):
        print(f"  Step {i+1}: {expected} ✓")
    
    return True


if __name__ == "__main__":
    # Print all available workflows
    print("Available Test Workflows:")
    print("=" * 50)
    
    for app_name, workflows in get_test_workflows().items():
        print(f"\n{app_name.upper()}:")
        for workflow in workflows:
            print(f"  - {workflow['task_query']}")
    
    # Run async examples
    # asyncio.run(run_workflow_examples())
