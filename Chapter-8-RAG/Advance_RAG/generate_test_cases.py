import csv
import random

def generate_vwo_test_cases(filename, num_cases=5000):
    modules = ["Login", "Signup", "A/B Testing", "Heatmaps", "Session Recordings", "Surveys", "Funnel Analysis", "Integrations", "Account Settings"]
    priorities = ["High", "Medium", "Low", "Critical"]
    actions = ["Create", "Edit", "Delete", "View", "Filter", "Export", "Search", "Toggle"]
    components = ["Campaign", "Variation", "Goal", "Segment", "User Role", "Dashboard Widget", "API Key", "Snapshot"]
    
    headers = [
        "Issue Type", "Summary", "Description", "Priority", "Labels", 
        "Test Steps", "Test Data", "Expected Result", "Status"
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        for i in range(1, num_cases + 1):
            module = random.choice(modules)
            action = random.choice(actions)
            comp = random.choice(components)
            priority = random.choice(priorities)
            
            summary = f"VWO - {module}: Verify user can {action.lower()} {comp.lower()} - ID_{i:04d}"
            description = f"This test case validates the {action.lower()} functionality for the {comp.lower()} component within the {module} module of app.vwo.com."
            labels = f"vwo,automated,{module.lower().replace(' ', '_')}"
            
            # Simulated steps
            steps = f"1. Log in to app.vwo.com\n2. Navigate to {module}\n3. Perform {action} action on {comp}\n4. Verify success message"
            test_data = f"user_role: admin, component_id: {random.randint(1000, 9999)}"
            expected_result = f"The {comp.lower()} should be successfully {action.lower()}ed and reflected in the {module} dashboard."
            
            writer.writerow([
                "Test",
                summary,
                description,
                priority,
                labels,
                steps,
                test_data,
                expected_result,
                "To Do"
            ])

if __name__ == "__main__":
    file_path = "testcases.csv"
    print(f"Generating 5000 test cases for VWO...")
    generate_vwo_test_cases(file_path, 5000)
    print(f"Successfully generated {file_path}")
