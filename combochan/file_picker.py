"""Native path selection is optional: the dashboard also accepts pasted paths."""
import json
import sys


def main():
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
    kind=sys.argv[1]
    types=[('FBNeo executable','*.exe')] if kind=='emulator' else [('FBNeo save state','*.fs')]
    if kind=='snapshots':
        result={'paths':list(filedialog.askopenfilenames(title='Add save states to queue',filetypes=types,parent=root))}
    else:
        result={'path':filedialog.askopenfilename(title='Select '+kind,filetypes=types,parent=root)}
    root.destroy()
    print(json.dumps(result))


if __name__=='__main__': main()
