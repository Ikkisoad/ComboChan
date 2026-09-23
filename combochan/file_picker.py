"""Native path selection is optional: the dashboard also accepts pasted paths."""
import json
import sys


def main():
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
    kind=sys.argv[1]
    types=[('FBNeo executable','*.exe')] if kind=='emulator' else [('FBNeo save state','*.fs')]
    path=filedialog.askopenfilename(title='Select '+kind,filetypes=types,parent=root)
    root.destroy()
    print(json.dumps({'path':path}))


if __name__=='__main__': main()
