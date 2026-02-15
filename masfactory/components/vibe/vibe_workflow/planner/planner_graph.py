from masfactory import Loop,NodeTemplate,HumanFileEditVisual
from .planner_diagnose_loop import PlannerDiagnoseLoop
def terminate_check(messages:dict):
   user_advice:str = messages.get("user_advice","")
   if len(user_advice.strip()) == 0 or "agree" in user_advice.lower():
      return True
   else:
      return False

PlannerHuman = NodeTemplate(
   HumanFileEditVisual,
   pull_keys={},
   push_keys={},
)

# PlannerGraph = NodeTemplate(
#    Loop,
#    pull_keys={},
#    push_keys={},
#    terminate_condition_function=terminate_check,
#    nodes=[
#       ("planner",Planner),
#       ("planner-human",PlannerHuman)
#    ],
#    edges=[
#       ("CONTROLLER","planner",
#          {
#             "user_demand":"",
#             "role_list":"",
#             "user_advice":"No advice yet."
#          }
#       ),
#       ("planner","planner-human",
#          {
#             "graph_design":"The generated graph design accroding to the user's demand and the roles."
#          }
#       ),
#       ("planner","CONTROLLER",
#          {
#             "graph_design":"The generated graph design accroding to the user's demand and the roles."
#          }
#       ),
#       ("planner-human","CONTROLLER",
#          {
#             "user_advice":"Do you agree the plan? If you agree, enter AGREE. If you have any comments, please enter your comments."
#          }
#       )
#    ]
# )

PlannerGraph = NodeTemplate(
    Loop,
    terminate_condition_function=terminate_check,
    pull_keys={"cache_file_path":""},
    push_keys={},
   nodes=[
      ("planner-diagnose-loop",PlannerDiagnoseLoop),
      ("planner-human",PlannerHuman)
   ],
    edges=[
        (
            "CONTROLLER","planner-diagnose-loop",
            {
                "user_demand": "User demand", 
                "role_list": "Role list",
                "user_advice":"User's feedback"
            },
        ),
        (
            "planner-diagnose-loop","planner-human",
            {
                "graph_design":"The generated graph design accroding to the user's demand and the roles."
            },
        ),
        (
            "planner-human","CONTROLLER",
            {
                "user_advice":"Do you agree the plan? If you agree, enter AGREE. If you have any comments, please enter your comments."
            }
        ),
        (
            "planner-diagnose-loop","CONTROLLER",
            {
                "graph_design":"The generated graph design accroding to the user's demand and the roles."
            }
        )
    ],
)

__ALL__=[
    'PlannerGraph'
]