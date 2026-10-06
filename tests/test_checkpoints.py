"""Protocol checks and optional Lua 5.1 runner integration with a toy emulator."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest

from combochan.bridge import Step, Trial


class CheckpointTests(unittest.TestCase):
    def test_prefix_must_leave_a_continuation(self):
        steps=(Step(8,('LP',)),Step(1,('HP',)))
        Trial('route',steps,checkpoint_steps=1).validate()
        for value in (-1,2,True,1.5):
            with self.subTest(value=value),self.assertRaises(ValueError):
                Trial('route',steps,checkpoint_steps=value).validate()

    @unittest.skipUnless(os.environ.get('COMBOCHAN_TEST_LUA51'), 'Set COMBOCHAN_TEST_LUA51 to a Lua 5.1 shared library')
    def test_lua_cached_prefix_matches_full_root_replay(self):
        dll=ctypes.CDLL(os.environ['COMBOCHAN_TEST_LUA51'])
        dll.luaL_newstate.restype=ctypes.c_void_p
        dll.luaL_openlibs.argtypes=[ctypes.c_void_p]
        dll.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        dll.lua_pcall.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        dll.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        dll.lua_tolstring.restype=ctypes.c_char_p
        dll.lua_close.argtypes=[ctypes.c_void_p]
        runner=(Path(__file__).resolve().parents[1]/'bridge/runner.lua').as_posix()
        results=[]
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'root.fs').write_bytes(b'root')
                extra='\t1' if enabled else ''
                (root/'request.tsv').write_text('COMBOCHAN1\ttest\troot.fs\tturbo\n'+
                    f'a\t1\t10\tneutral\t8:LP;1:HP{extra}\n'+
                    f'b\t1\t10\tneutral\t8:LP;1:HK{extra}\n')
                script='COMBOCHAN_BRIDGE_DIR = '+json.dumps(root.as_posix()+'/')+'\n'+r'''
local hp, held, states=288,{},{}
local advances=0
local names={"Up","Down","Left","Right","Weak Punch","Medium Punch","Strong Punch","Weak Kick","Medium Kick","Strong Kick"}
local inputs={};for p=1,2 do for _,name in ipairs(names) do inputs["P"..p.." "..name]=false end end
joypad={get=function() return inputs end,set=function(t) held=t end}
memory={readbyte=function() return 0 end,readwordsigned=function() return 0 end,
 readword=function(address) if address==0xFF8850 then return hp elseif address==0xFF8450 then return 288 end return 0 end}
savestate={load=function(path) hp=states[path] or 288 end,
 save=function(path) states[path]=hp;local f=assert(io.open(path,'wb'));f:write('toy');f:close() end}
emu={romname=function() return 'vsavj' end,speedmode=function() end,registerexit=function() end,
 frameadvance=function()
  local f=io.open(COMBOCHAN_BRIDGE_DIR..'test.jsonl','rb')
  if f then f:close();local count=assert(io.open(COMBOCHAN_BRIDGE_DIR..'count','w'));count:write(advances);count:close();error('TEST_DONE') end
  advances=advances+1
  if held['P1 Weak Punch'] or held['P1 Strong Punch'] or held['P1 Strong Kick'] then hp=hp-1 end
 end}
'''+'\nreturn assert(loadfile('+json.dumps(runner)+'))()'
                state=dll.luaL_newstate()
                try:
                    dll.luaL_openlibs(state)
                    status=dll.luaL_loadstring(state,script.encode())
                    if not status: status=dll.lua_pcall(state,0,0,0)
                    message=dll.lua_tolstring(state,-1,None).decode() if status else ''
                    self.assertIn('TEST_DONE',message)
                finally: dll.lua_close(state)
                rows=[json.loads(line) for line in (root/'test.jsonl').read_text().splitlines()]
                self.assertEqual(list(root.glob('checkpoint_*.fs')),[])
                results.append((rows,int((root/'count').read_text())))
        self.assertEqual([r['trace'] for r in results[0][0]],[r['trace'] for r in results[1][0]])
        self.assertEqual(results[1][0][1]['checkpoint_frames'],8)
        self.assertEqual(results[0][1]-results[1][1],8)


if __name__=='__main__': unittest.main()
