"""Reproduces the internal dashboard's bug report: it calls the tool named
'list_widgets' against toy-consumer's live app and gets 'tool not found'.
"""

from toy_consumer.app import app

names = [t.name for t in app.list_tools()]
print("Tools actually exposed on the app:", names)

if "list_widgets" in names:
    print("OK: list_widgets is callable.")
else:
    print("BUG REPRODUCED: 'list_widgets' is NOT among the exposed tools.")
