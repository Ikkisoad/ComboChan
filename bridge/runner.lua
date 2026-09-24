-- Standalone Lua 5.1 runner for Fightcade FBNeo. Replaces the training script.
-- No gameplay memory writes, health refill, or meter refill.
local source = debug.getinfo(1, "S").source:sub(2):gsub("\\", "/")
local root = assert(source:match("^(.*)/bridge/runner.lua$"), "Use absolute script path")
local dir = COMBOCHAN_BRIDGE_DIR or (root .. "/artifacts/bridge/")
local rb, rw, rs = memory.readbyte, memory.readword, memory.readwordsigned
local config = COMBOCHAN_GAME
local expected_rom = config and config.rom or "vsavj"
assert(emu.romname() == expected_rom, "Wrong ROM for selected game profile")
local function read_field(spec)
    local readers = {u8=rb, u16=rw, s16=rs}
    local value = readers[spec.type](spec.address)
    if spec.mask then
        local result, place, mask = 0, 1, spec.mask
        while mask > 0 do
            if mask % 2 == 1 and value % 2 == 1 then result = result + place end
            value = math.floor(value / 2); mask = math.floor(mask / 2); place = place * 2
        end
        value = result
    end
    if spec.equals ~= nil then value = value == spec.equals and 1 or 0 end
    return value
end
local function position(player)
    if config then return read_field(config.players[player].x) end
    return rs(player == "p1" and 0xFF8410 or 0xFF8810)
end
local function input_key(player, code)
    if config then return assert(config.inputs[code], "Unmapped input: "..code)[player] end
    local default = {U="Up",D="Down",L="Left",R="Right",LP="Weak Punch",MP="Medium Punch",
        HP="Strong Punch",LK="Weak Kick",MK="Medium Kick",HK="Strong Kick"}
    return (player == "p1" and "P1 " or "P2 ") .. assert(default[code])
end

local function encode(v)
    if type(v) == "string" then
        return '"' .. v:gsub('[%z\1-\31\\"]', function(c)
            return string.format("\\u%04x", c:byte())
        end) .. '"'
    elseif type(v) == "number" or type(v) == "boolean" then return tostring(v)
    elseif type(v) == "table" then
        local parts = {}
        if #v > 0 then
            for _, x in ipairs(v) do parts[#parts+1] = encode(x) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, x in pairs(v) do parts[#parts+1] = encode(k) .. ":" .. encode(x) end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

local function write_atomic(path, value)
    local f = assert(io.open(path .. ".tmp", "wb"))
    f:write(encode(value)); f:close()
    os.remove(path)
    assert(os.rename(path .. ".tmp", path))
end

local names = {"Up", "Down", "Left", "Right", "Weak Punch", "Medium Punch",
    "Strong Punch", "Weak Kick", "Medium Kick", "Strong Kick"}
local codes = {F="Forward",B="Back",U="Up",D="Down",L="Left",R="Right",LP="Weak Punch",MP="Medium Punch",
    HP="Strong Punch",LK="Weak Kick",MK="Medium Kick",HK="Strong Kick"}
local input_names = joypad.get()
if config then
    codes = {F=true,B=true}
    for code, mapping in pairs(config.inputs) do
        codes[code] = true
        for _, key in pairs(mapping) do
            assert(type(input_names[key]) == "boolean", "Missing input: "..key)
        end
    end
else
    for p=1,2 do
        for _, name in ipairs(names) do
            assert(input_names["P"..p.." "..name] ~= nil, "Missing input: P"..p.." "..name)
        end
    end
end
local function controls(buttons, defense, hit_seen)
    local t = {}
    -- Explicit false overrides physical controller state; nil does not.
    for name, value in pairs(input_names) do
        if type(value) == "boolean" then t[name] = false end
    end
    for _, name in ipairs(buttons) do
        assert(codes[name], "Unknown button")
        local code = name
        if name == "F" or name == "B" then
            local right = position("p1") <= position("p2")
            if name == "B" then right = not right end
            code = right and "R" or "L"
        end
        t[input_key("p1", code)] = true
    end
    if defense ~= "neutral" and hit_seen then
        local away = position("p2") >= position("p1") and "R" or "L"
        t[input_key("p2", away)] = true
        if defense == "crouch" then t[input_key("p2", "D")] = true end
        if defense == "jump" then t[input_key("p2", "U")] = true end
    end
    return t
end
local function player(base)
    return {health=rw(base+0x50), recoverable=rw(base+0x52),
        stocks=rb(base+0x109), meter=rw(base+0x10A), facing=rb(base+0x120),
        -- +0x144 counts hits received; nonzero alone does not prove continuity.
        combo_hits=rb(base+0x144), stun1=rb(base+0x144), stun2=rb(base+0x145),
        x=rs(base+0x10), y=rs(base+0x14), state=rw(base+4)}
end
local function configured_player(id)
    local values = {recoverable=0,stocks=0,meter=0,facing=0,stun2=0,y=0,state=0}
    for name, spec in pairs(config.players[id]) do values[name] = read_field(spec) end
    return values
end
local function sample(frame)
    if config then return {frame=frame,p1=configured_player("p1"),p2=configured_player("p2")} end
    return {frame=frame,p1=player(0xFF8400),p2=player(0xFF8800)}
end
local function split(line)
    local out = {}
    for field in (line .. "\t"):gmatch("(.-)\t") do out[#out+1] = field end
    return out
end
local function integer(s, min, max)
    local n=tonumber(s)
    assert(n and n==math.floor(n) and n>=min and n<=max, "Invalid integer")
    return n
end
local function read_job()
    local f = io.open(dir .. "request.tsv", "rb")
    if not f then return nil end
    local data=f:read(1048577); f:close()
    assert(#data <= 1048576, "Request too large")
    local lines={}
    for line in data:gmatch("[^\r\n]+") do lines[#lines+1]=split(line) end
    local h=assert(lines[1]); assert(h[1]=="COMBOCHAN1" and #h==4, "Bad header")
    assert(h[2]:match("^[%w_-]+$"), "Bad request ID")
    assert(h[3]:match("^[%w_-]+%.fs$"), "Snapshot must be in bridge directory")
    assert(h[4]=="normal" or h[4]=="turbo", "Bad speed")
    local trials={}
    for i=2,#lines do
        local r=lines[i]
        assert(#r==5 and r[1]:match("^[%w_-]+$"), "Bad trial")
        local trial={id=r[1], repeats=integer(r[2],1,100), tail=integer(r[3],1,600), defense=r[4], steps={}}
        assert(trial.defense=="neutral" or trial.defense=="stand" or trial.defense=="crouch" or trial.defense=="jump", "Bad defense")
        local total=trial.tail
        for step in r[5]:gmatch("[^;]+") do
            local n, buttons=step:match("^(%d+):(.*)$")
            local duration=integer(n,1,240); total=total+duration
            local held={}
            for button in buttons:gmatch("[^,]+") do assert(codes[button], "Unknown button"); held[#held+1]=button end
            trial.steps[#trial.steps+1]={frames=duration,buttons=held}
        end
        assert(total<=1200 and #trial.steps>0, "Trial duration out of bounds")
        trials[#trials+1]=trial
    end
    assert(#trials>0 and #trials<=512, "Bad trial count")
    local snapshot=dir..h[3]
    local sf=assert(io.open(snapshot,"rb"), "Missing snapshot"); sf:close()
    assert(os.rename(dir.."request.tsv",dir..h[2]..".accepted.tsv"))
    return {id=h[2],snapshot=snapshot,speed=h[4],trials=trials}
end

emu.registerexit(function() emu.speedmode("normal") end)
local script_file = assert(io.open(source,"rb"))
local script_content = script_file:read("*a"); script_file:close()
write_atomic(dir.."ready.json",{protocol=1,rom=emu.romname(),inputs=input_names,script=source,script_content=script_content,profile_sha256=config and config.sha256 or nil})
local last_heartbeat = 0
local function heartbeat()
    local now = os.time()
    if now ~= last_heartbeat then
        write_atomic(dir.."heartbeat.json",{time=now,rom=emu.romname()})
        last_heartbeat = now
    end
end
print("ComboChan ready. Requests: " .. dir)
while true do
    heartbeat()
    local ok, job = pcall(read_job)
    if not ok then
        write_atomic(dir.."error.json",{error=tostring(job)}); error(job)
    end
    if job then
        emu.speedmode(job.speed)
        local path=dir..job.id..".jsonl"
        local output=assert(io.open(path..".tmp","wb"))
        for _, trial in ipairs(job.trials) do
            for repetition=1,trial.repeats do
                savestate.load(job.snapshot)
                assert(emu.romname() == expected_rom, "The selected save state has the wrong ROM")
                local trace={sample(0)}
                local baseline=trace[1].p2.health
                local frame = 0
                -- Existing combos must face escape attempts from the first restored frame.
                local hit_seen = trace[1].p2.stun1 ~= 0 or trace[1].p2.stun2 ~= 0
                local steps={}
                for _,s in ipairs(trial.steps) do steps[#steps+1]=s end
                steps[#steps+1]={frames=trial.tail,buttons={}}
                for _, step in ipairs(steps) do
                    for _=1,step.frames do
                        joypad.set(controls(step.buttons,trial.defense,hit_seen))
                        emu.frameadvance()
                        heartbeat()
                        frame=frame+1
                        local observation=sample(frame)
                        trace[#trace+1]=observation
                        if observation.p2.health<baseline then hit_seen=true end
                    end
                end
                output:write(encode({id=trial.id,repetition=repetition,defense=trial.defense,trace=trace}).."\n")
                output:flush()
            end
        end
        output:close()
        assert(os.rename(path..".tmp",path))
        savestate.load(job.snapshot)
        emu.speedmode("normal")
        print("Completed "..job.id)
    end
    joypad.set(controls({},"neutral",false))
    emu.frameadvance()
end
