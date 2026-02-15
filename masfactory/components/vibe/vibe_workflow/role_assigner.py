from masfactory import (
   Agent,
   HistoryMemory,
   HumanChatVisual,
   Loop,
   NodeTemplate,
   ParagraphMessageFormatter,
   TwinsFieldTextFormatter,
)
INSTRUCTIONS = """
Here is the translation, formatted for you to copy directly:

You are an expert-level Agent Team Architect and Role Allocator. Your task is to analyze complex user requirements and identify the names of the professional roles (Agents) required to complete the task.

Instructions:
Analyze Requirements: Understand the user's core goals and the specific domain knowledge required to complete the task.

Define Roles: Identify the set of Agents needed to form a complete team. Ensure a clear division of labor and complete coverage of the requirements.

Output Format (Strict Adherence):
Please strictly adhere to the following format. Do not use Markdown code blocks or JSON. Output only the number and the role name. Do not output extraneous content such as role responsibilities or input/output descriptions.

EXAMPLES:
[ROLES] 
1: <Role Name 1> 
2: <Role Name 2> 
...
"""

PROMPT_TEXT="""
The user's initial demand is:
{user_demand}

And for the previous version of the plan, the user's suggestion was:
{user_advice}
"""
RoleAssigner = NodeTemplate(
   Agent,
   instructions=INSTRUCTIONS,
   prompt_template=PROMPT_TEXT,
   formatters = [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
   memories=[HistoryMemory()]   
)


RoleAssignerHuman = NodeTemplate(
   HumanChatVisual,
   pull_keys={},
   push_keys={},
)
def terminate_check(messages:dict):
   user_advice:str = messages.get("user_advice","")
   if len(user_advice.strip()) == 0 or "agree" in user_advice.lower():
      return True
   else:
      return False

RoleAssignerGraph = NodeTemplate(
   Loop,
   pull_keys={},
   push_keys={},
   terminate_condition_function=terminate_check,
   nodes=[
      ("role-assigner",RoleAssigner),
      ("role-assigner-human",RoleAssignerHuman)
   ],
   edges=[
      ("CONTROLLER","role-assigner",{"user_demand":"","user_advice":"No advice yet."}),
      ("role-assigner","role-assigner-human",{"role_list":"The generated roles and descriptions accroding to the user's demand."}),
      ("role-assigner","CONTROLLER",{"role_list":"The generated roles and descriptions accroding to the user's demand."}),
      ("role-assigner-human","CONTROLLER",{"user_advice":"Do you agree the plan? If you agree, enter AGREE. If you have any comments, please enter your comments."})
   ]
)

__ALL__=[
   "RoleAssignerGraph"
]
