"""A windowed interface for the terminal: buttons, text boxes, lists and dialogs.

    python -m robot.tui

It runs saved instructions, shows the run as it goes, and edits the instruction
library and the skills. Everything is drawn with characters, so it works on
the Pi's own screen and over SSH; no graphical desktop is involved.

The pieces:
    text.py     measuring and wrapping text, and the text behind a text box
    screen.py   the screen and the keyboard (curses is used here and only here)
    widgets.py  buttons, check boxes, text boxes, lists, and the window they sit in
    dialogs.py  small windows: a message, a question, a choice, a text
    editor.py   the Instruction Editor
    skillsui.py the Skills Manager
    app.py      the main window, and how a run and the screen work side by side
"""
