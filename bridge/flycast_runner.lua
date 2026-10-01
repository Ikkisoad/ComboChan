-- Flycast Dojo Lua 5.3 runner for MVC2 Naomi. No gameplay-memory writes.
-- Restores happen on the UI/overlay thread; inputs and telemetry on VBlank.
local source = debug.getinfo(1, 'S').source:sub(2):gsub('\\', '/')
local dir = assert(COMBOCHAN_BRIDGE_DIR, 'Load the prepared session bootstrap')
local runtime = assert(COMBOCHAN_RUNTIME_DIR, 'Launch the isolated Flycast copy')
local memory, input = flycast.memory, flycast.input
-- Naomi buttons 3 and 6 use Dreamcast C and Z bits in Flycast's JVS map.
local codes = {U=16,D=32,L=64,R=128,LP=4,HP=2,LK=1024,HK=512,A1=1,A2=256,F=true,B=true}
local JSON_NULL = {}
local function encode(v)
    if v==JSON_NULL then return 'null'
    elseif type(v)=='string' then
        return '"'..v:gsub('[%z\1-\31\\"]',function(c) return string.format('\\u%04x',c:byte()) end)..'"'
    elseif type(v)=='number' then
        assert(v==v and v~=math.huge and v~=-math.huge,'Invalid numeric telemetry')
        return tostring(v)
    elseif type(v)=='boolean' then return tostring(v)
    elseif type(v)=='table' then
        local out={}
        if #v>0 then
            for _,x in ipairs(v) do out[#out+1]=encode(x) end
            return '['..table.concat(out,',')..']'
        end
        for k,x in pairs(v) do out[#out+1]=encode(k)..':'..encode(x) end
        return '{'..table.concat(out,',')..'}'
    end
    return 'null'
end
local function write_atomic(path,value)
    local f=assert(io.open(path..'.tmp','wb'));f:write(encode(value));f:close()
    os.remove(path);assert(os.rename(path..'.tmp',path))
end
local function copy_file(from,to)
    local src=assert(io.open(from,'rb'),'Missing session snapshot')
    local dst=assert(io.open(to..'.tmp','wb'))
    while true do local chunk=src:read(65536);if not chunk then break end;dst:write(chunk) end
    src:close();dst:close();os.remove(to);assert(os.rename(to..'.tmp',to))
end
local function release()
    for p=1,2 do
        input.releaseButtons(p,0xffffffff)
        for axis=1,6 do input.setAxis(p,axis,0) end
    end
end
local point_slots={}
local function player(p)
    local team,active,slot,flags,characters,positions={},0,1,{},{},{}
    for i=1,3 do
        local base=0x0c2d7088+(p-1)*0x5a4+(i-1)*0xb48
        team[i]=memory.read16(base+0x420)
        flags[i]=memory.read8(base)
        characters[i]=memory.read8(base+1)
        positions[i]=flags[i]==1 and {x=memory.read32f(base+0x34),y=memory.read32f(base+0x38)} or JSON_NULL
        if flags[i]==1 then active=active+1;if active==1 then slot=i end end
    end
    if point_slots[p] and flags[point_slots[p]]==1 then slot=point_slots[p] end
    if not point_slots[p] then point_slots[p]=slot end
    local base=0x0c2d7088+(p-1)*0x5a4+(slot-1)*0xb48
    -- Unknown hitstun is null in JSON, never a fabricated zero.
    return {health=team[slot],team_health=team,team_active=flags,team_characters=characters,
        team_positions=positions,slot=slot,active_count=active,
        character=memory.read8(base+1),facing=memory.read8(base+0x110),
        x=memory.read32f(base+0x34),y=memory.read32f(base+0x38),
        stocks=memory.read8(0x0c2f8392+p-1),
        stun1=JSON_NULL,stun2=JSON_NULL,recoverable=JSON_NULL}
end
local function sample(frame)
    local a,b=player(1),player(2)
    -- JSON null placeholders keep the common worker contract explicit.
    local result={frame=frame,p1=a,p2=b,in_match=memory.read8(0x0c2f836c)}
    return result
end
local function encode_record(record)
    return encode(record)
end
local function controls(buttons,defense,hit_seen)
    release()
    local mask=0
    for _,name in ipairs(buttons) do
        local code=name
        if name=='F' or name=='B' then
            local right=player(1).x<=player(2).x
            if name=='B' then right=not right end
            code=right and 'R' or 'L'
        end
        mask=mask | assert(codes[code],'Unsupported input')
    end
    input.pressButtons(1,mask)
    if hit_seen and defense~='neutral' then
        local away=player(2).x>=player(1).x and codes.R or codes.L
        if defense=='crouch' then away=away | codes.D end
        if defense=='jump' then away=away | codes.U end
        input.pressButtons(2,away)
    end
end
local function split(line)
    local out={};for field in (line..'\t'):gmatch('(.-)\t') do out[#out+1]=field end;return out
end
local function integer(s,low,high)
    local n=tonumber(s);assert(n and n==math.floor(n) and n>=low and n<=high,'Invalid integer');return n
end
local function read_job()
    local f=io.open(dir..'request.tsv','rb');if not f then return end
    local data=f:read(1048577);f:close();assert(#data<=1048576,'Request too large')
    local lines={};for line in data:gmatch('[^\r\n]+') do lines[#lines+1]=split(line) end
    local h=assert(lines[1]);assert(#h==4 and h[1]=='COMBOCHAN1','Bad header')
    assert(h[2]:match('^[%w_-]+$'),'Bad job ID')
    assert(h[3]:match('^[%w_-]+%.state$'),'Invalid snapshot filename')
    assert(h[4]=='normal' or h[4]=='turbo','Bad speed')
    local trials,ids={},{}
    for i=2,#lines do
        local r=lines[i];assert(#r==5 and r[1]:match('^[%w_-]+$') and not ids[r[1]],'Bad trial')
        ids[r[1]]=true
        assert(r[4]=='neutral' or r[4]=='stand' or r[4]=='crouch' or r[4]=='jump','Bad defense')
        local t={id=r[1],repeats=integer(r[2],1,100),tail=integer(r[3],1,600),defense=r[4],steps={}}
        local total=t.tail
        for token in r[5]:gmatch('[^;]+') do
            local n,buttons=token:match('^(%d+):(.*)$');local duration=integer(n,1,240)
            local held,seen={},{}
            for button in buttons:gmatch('[^,]+') do
                assert(codes[button] and not seen[button],'Unknown or duplicate input')
                seen[button]=true;held[#held+1]=button
            end
            assert(not (seen.L and seen.R or seen.U and seen.D or seen.F and seen.B),'Opposing directions')
            t.steps[#t.steps+1]={frames=duration,buttons=held};total=total+duration
        end
        assert(total<=1200 and #t.steps>0,'Invalid duration')
        t.steps[#t.steps+1]={frames=t.tail,buttons={}};t.total=total
        trials[#trials+1]=t
    end
    assert(#trials>0 and #trials<=512,'Invalid trial count')
    copy_file(dir..h[3],runtime..'data/mvsc2_9.state')
    assert(os.rename(dir..'request.tsv',dir..h[2]..'.accepted.tsv'))
    return {id=h[2],trials=trials,index=1,repetition=1}
end
local game_started,ready,failed=false,false,false
local frame_count,last_heartbeat=0,0
local job,trace,output=nil,nil,nil
local phase='idle'
local loaded=false
local hit_seen=false
local function assert_game()
    assert(flycast.state.media:gsub('\\','/'):match('/mvsc2%.zip$'),'MVC2 Naomi ROM required')
    assert(flycast.state.gameId:match('MARVEL VS CAPCOM2'),'Wrong game ID')
end
local function restore()
    phase='loading';loaded=false;point_slots={};release()
    flycast.emulator.loadState(9)
    assert(loaded,'Flycast did not confirm snapshot restoration')
    assert_game();phase='first'
end
local function heartbeat()
    local now=os.time()
    if now~=last_heartbeat then
        write_atomic(dir..'heartbeat.json',{time=now,rom='mvsc2',phase=phase,
            trial=job and job.index,repetition=job and job.repetition,
            trace_frames=trace and #trace,vblanks=frame_count})
        last_heartbeat=now
    end
end
local function fail(err)
    if failed then return end
    failed=true;phase='failed';release()
    if output then output:close();output=nil end
    os.remove(dir..'heartbeat.json')
    write_atomic(dir..'error.json',{error=tostring(err)})
end
local function vblank()
    if failed then return end
    frame_count=frame_count+1
    if not ready then return end
    heartbeat()
    if phase=='first' then
        trace={sample(0)};phase='running';hit_seen=false
        controls(job.trials[job.index].steps[1].buttons,job.trials[job.index].defense,false)
    elseif phase=='running' then
        local trial=job.trials[job.index]
        local frame=#trace
        trace[#trace+1]=sample(frame)
        if trace[#trace].p2.health<trace[#trace-1].p2.health then hit_seen=true end
        if frame==trial.total then phase='finished';release();return end
        local remaining=frame
        for _,step in ipairs(trial.steps) do
            if remaining<step.frames then controls(step.buttons,trial.defense,hit_seen);break end
            remaining=remaining-step.frames
        end
    else release() end
end
local function overlay()
    if failed or not game_started or frame_count<120 then return end
    if not ready then
        assert_game()
        assert(type(memory.read32f)=='function','Flycast Dojo 6.32+ is required')
        copy_file(dir..'root.state',runtime..'data/mvsc2_9.state')
        restore();phase='idle'
        local f=assert(io.open(source,'rb'));local content=f:read('*a');f:close()
        write_atomic(dir..'ready.json',{protocol=1,rom='mvsc2',backend='flycast',
            script=source,script_content=content,profile_sha256=COMBOCHAN_PROFILE_SHA256,
            actual_speed='normal',game_id=flycast.state.gameId})
        ready=true;heartbeat()
    end
    if phase=='finished' then
        local trial=job.trials[job.index]
        output:write(encode_record({id=trial.id,repetition=job.repetition,defense=trial.defense,trace=trace})..'\n');output:flush()
        job.repetition=job.repetition+1
        if job.repetition>trial.repeats then job.index=job.index+1;job.repetition=1 end
        if job.index>#job.trials then
            output:close();output=nil
            restore();phase='idle'
            assert(os.rename(dir..job.id..'.jsonl.tmp',dir..job.id..'.jsonl'))
            job=nil
        else restore() end
    elseif phase=='idle' then
        job=read_job()
        if job then
            output=assert(io.open(dir..job.id..'.jsonl.tmp','wb'))
            restore()
        end
    end
end
flycast_callbacks={
    start=function() game_started=true end,
    loadState=function() loaded=true end,
    vblank=function() local ok,err=pcall(vblank);if not ok then fail(err) end end,
    overlay=function() local ok,err=pcall(overlay);if not ok then fail(err) end end,
    terminate=function() release();os.remove(dir..'heartbeat.json') end,
}
