from masfactory import RootGraph, OpenAIModel
from masfactory.adapters.model import Model
from masfactory.components.custom_node import CustomNode
from typing import Literal, Optional
from pathlib import Path
from .components import (
    ProductManagerAgent,
    ArchitectAgent,
    ProjectManagerAgent,
    QAEngineerAgent,
    requirement_preprocessor_forward,
    integration_checker_forward,
    test_executor_forward,
    result_assembler_forward,
)
from .dev_loop import DevLoop

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECTS_DIR = _PACKAGE_DIR / "projects"
_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

def create_software_company_graph(
    model: Model,
    project_name: str = "",
    max_dev_iterations: int = 40,
    max_retries_per_task: int = 3,
    enable_qa: bool = False,
    phase: Literal["full", "planning", "build"] = "full",
    preset_attributes: Optional[dict[str, object]] = None,
) -> RootGraph:
    """
    Build the MetaGPT software-company workflow graph with configurable
    iterations, retry policies, and optional QA stages.
    """
    phase = (phase or "full").lower()
    if phase not in {"full", "planning", "build"}:
        raise ValueError(f"Unsupported workflow phase: {phase}")
    target_dir = _PROJECTS_DIR / (project_name if project_name else "default")
    project_path = str(target_dir)
    root_attributes: dict[str, object] = {
        "project_path": project_path,
        "project_name": project_name,
    }
    if preset_attributes:
        for key, value in preset_attributes.items():
            if value is not None:
                root_attributes[key] = value
    root = RootGraph(
        name="software_company",
        attributes=root_attributes,
    )
    include_planning = phase in {"planning", "full"}
    include_build = phase in {"build", "full"}
    

    req_preprocessor = None
    if include_planning:
        req_preprocessor = root.create_node(
            CustomNode,
            name="requirement_preprocessor",
            forward=requirement_preprocessor_forward,
            pull_keys={
                "raw_requirement": "Raw requirement from user",
            },
            push_keys={
                "requirement": "Normalized requirement",
            },
        )
    

    product_manager = None
    if include_planning:
        product_manager = root.create_node(
            ProductManagerAgent,
            name="product_manager",
            model=model,
            pull_keys={
                "requirement": "Normalized requirement from RequirementPreprocessor",
            },
            push_keys={
                "prd": "Product Requirement Document",
                "user_stories": "List of user stories",
                "requirement_pool": "List of requirements",
            },
        )
    

    architect = None
    if include_planning:
        architect = root.create_node(
            ArchitectAgent,
            name="architect",
            model=model,
            pull_keys={
                "prd": "Product Requirement Document from Product Manager",
                "requirement_pool": "Requirement pool from Product Manager (optional)",
            },
            push_keys={
                "system_design": "System design document",
                "file_list": "List of files to be created",
                "data_structures": "Data structure definitions",
                "api_specs": "API specifications",
            },
        )
    

    project_manager = None
    if include_planning:
        project_manager = root.create_node(
            ProjectManagerAgent,
            name="project_manager",
            model=model,
            pull_keys={
                "system_design": "System design from Architect",
                "file_list": "File list from Architect",
                "user_stories": "User stories from Product Manager (optional)",
            },
            push_keys={
                "task_list": "List of tasks to be implemented",
            },
        )
    

    dev_loop = None
    if include_build:
        dev_loop = root.create_node(
            DevLoop,
            name="dev_loop",
            model=model,
            max_iterations=max_dev_iterations,
            max_retries_per_task=max_retries_per_task,
            attributes={
                "project_path": project_path,
            },
            pull_keys={
                "task_list": "Task list from Project Manager",
                "system_design": "System design from Architect",
                "project_path": "Project path (from root attributes)",
            },
            push_keys={
                "codebase": "Complete codebase with all implemented files",
            },
        )
    

    integration_checker = None
    if include_build:
        integration_checker = root.create_node(
            CustomNode,
            name="integration_checker",
            forward=integration_checker_forward,
            pull_keys={
                "codebase": "Complete codebase from DevLoop",
                "project_path": "Project path (from root attributes)",
            },
            push_keys={
                "codebase": "Codebase (possibly with fixes)",
                "integration_check_report": "Integration check report",
                "integration_status": "Integration status",
            },
        )
    
    qa_engineer = None
    test_executor = None
    if enable_qa and include_build:

        qa_engineer = root.create_node(
            QAEngineerAgent,
            name="qa_engineer",
            model=model,
            pull_keys={
                "codebase": "Complete codebase from DevLoop",
                "prd": "Product Requirement Document",
                "system_design": "System design document",
            },
            push_keys={
                "test_cases": "List of test case descriptions",
                "test_code": "Python test code that can be executed",
                "test_file_name": "Name of the test file",
            },
        )
        

        test_executor = root.create_node(
            CustomNode,
            name="test_executor",
            forward=test_executor_forward,
            pull_keys={
                "test_code": "Test code from QA Engineer",
                "test_file_name": "Test file name",
                "codebase": "Complete codebase",
                "project_path": "Project path (from root attributes)",
            },
            push_keys={
                "test_report": "Test execution report",
                "test_status": "Test execution status",
            },
        )
    


    result_assembler = None
    if include_build:
        result_assembler = root.create_node(
            CustomNode,
            name="result_assembler",
            forward=result_assembler_forward,
            pull_keys={
                "codebase": "Complete codebase",
                "test_report": "Test report from QA Engineer",
                "prd": "Product Requirement Document (from root attributes)",
                "system_design": "System design document (from root attributes)",
            },
            push_keys={
                "final_answer": "Final project report",
                "attachments": "Project attachments",
            },
        )
    

    
    # Entry -> RequirementPreprocessor
    if include_planning and req_preprocessor is not None:
        root.edge_from_entry(
            receiver=req_preprocessor,
            keys={
                "raw_requirement": "Raw requirement from user",
            }
        )
    
    # RequirementPreprocessor -> ProductManager
    if include_planning and req_preprocessor is not None and product_manager is not None:
        root.create_edge(
            sender=req_preprocessor,
            receiver=product_manager,
            keys={
                "requirement": "Normalized requirement",
            }
        )
    
    # ProductManager -> Architect

    if include_planning and product_manager is not None and architect is not None:
        root.create_edge(
            sender=product_manager,
            receiver=architect,
            keys={
                "prd": "Product Requirement Document",
                "requirement_pool": "Requirement pool",
            }
        )
    
    # Architect -> ProjectManager

    if include_planning and architect is not None and project_manager is not None:
        root.create_edge(
            sender=architect,
            receiver=project_manager,
            keys={
                "system_design": "System design document",
                "file_list": "File list",
            }
        )
    
    # ProjectManager -> DevLoop



    if include_build and dev_loop is not None:
        if include_planning and project_manager is not None:
            root.create_edge(
                sender=project_manager,
                receiver=dev_loop,
                keys={
                    "task_list": "Task list",
                }
            )
        else:
            root.edge_from_entry(
                receiver=dev_loop,
                keys={
                    "task_list": "Task list generated in planning phase",
                }
            )
    
    if include_build and dev_loop is not None and integration_checker is not None:
        root.create_edge(
            sender=dev_loop,
            receiver=integration_checker,
            keys={
                "codebase": "Complete codebase",
            }
        )
    
    # IntegrationChecker -> QAEngineer


    if enable_qa and qa_engineer and test_executor and integration_checker and result_assembler:
        root.create_edge(
            sender=integration_checker,
            receiver=qa_engineer,
            keys={
                "codebase": "Complete codebase (checked and possibly fixed)",
            }
        )
        
        # QAEngineer -> TestExecutor
        root.create_edge(
            sender=qa_engineer,
            receiver=test_executor,
            keys={
                "test_code": "Test code from QA Engineer",
                "test_file_name": "Test file name",
            }
        )
        
        # TestExecutor -> ResultAssembler
        root.create_edge(
            sender=test_executor,
            receiver=result_assembler,
            keys={
                "codebase": "Complete codebase",
                "test_report": "Test execution report",
            }
        )
    else:

        if include_build and integration_checker and result_assembler:
            root.create_edge(
                sender=integration_checker,
                receiver=result_assembler,
                keys={
                    "codebase": "Complete codebase",
                }
            )
    
    # ResultAssembler -> Exit
    if include_build and result_assembler is not None:
        root.edge_to_exit(
            sender=result_assembler,
            keys={
                "final_answer": "Final project report",
                "attachments": "Project attachments",
            }
        )
    elif include_planning and project_manager is not None:
        # Planning-only mode exits after generating the task list / planning artifacts
        root.edge_to_exit(
            sender=project_manager,
            keys={
                "task_list": "List of tasks to be implemented",
            }
        )
    

    root._product_manager = product_manager
    root._architect = architect
    root._dev_loop = dev_loop
    root._project_path = project_path
    
    return root


def main():
    """Run a sample MetaGPT software-company workflow end to end."""
    import os
    

    api_key = os.getenv("OPENAI_API_KEY") or ""
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or "https://api.openai.com/v1"
    if not api_key:
        raise SystemExit("Missing OpenAI API key: set OPENAI_API_KEY.")

    model = OpenAIModel(
        api_key=api_key,
        base_url=base_url,
        model_name="gpt-4o-mini"
    )
    

    graph = create_software_company_graph(
        model=model,
        project_name="calculator",
        max_dev_iterations=40,
        max_retries_per_task=3,
    )
    

    graph.build()
    

    print("=" * 80)
    print("MetaGPT Software Company Workflow")
    print("=" * 80)
    print(f"Project: Calculator")
    print("=" * 80)
    print("\nStarting workflow...\n")
    
    result, attributes = graph.invoke({
        "raw_requirement": "Create a simple calculator using Python. The calculator should support addition, subtraction, multiplication, and division. The calculator should be able to handle both integer and floating-point numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers. The calculator should be able to handle both complex and real numbers. The calculator should be able to handle both positive and negative numbers. The calculator should be able to handle both large and small numbers. The calculator should be able to handle both rational and irrational numbers"
    })
    

    print("\n" + "=" * 80)
    print("Workflow completed!")
    print("=" * 80)
    print("\nFinal Report:")
    print(result.get("final_answer", ""))
    print("\nAttachment Summary:")
    attachments = result.get("attachments", {})
    if isinstance(attachments, dict):
        print(f"- Code files: {len(attachments.get('codebase', {}))}")
        print(f"- PRD: {'available' if attachments.get('prd') else 'missing'}")
        print(f"- System design: {'available' if attachments.get('system_design') else 'missing'}")
        print(f"- Test report: {'available' if attachments.get('test_report') else 'missing'}")


if __name__ == "__main__":
    main()
