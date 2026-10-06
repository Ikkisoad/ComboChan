import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from combochan.dashboard_worker import execute
from combochan.bridge import Step
from combochan.dashboard import DEFAULT_RULES, validate_rules
from combochan.dashboard_worker import continuation_candidates, select_frontier, timing_options
from combochan.games import get_game
from combochan.moves import parse_sequence, parse_starter

class MovesAndTimingTests(unittest.TestCase):
    def test_numpad_special_sequence_and_validation(self):
        self.assertEqual(parse_sequence('41236LK'),(Step(2,('B',)),Step(2,('D','B')),
            Step(2,('D',)),Step(2,('D','F')),Step(1,('F','LK'))))
        self.assertEqual(parse_sequence('236lp+hp'),(Step(2,('D',)),Step(2,('D','F')),Step(1,('F','LP','HP'))))
        for text in ('41236K','41236P','01236LK','41236LK+LK','2'*65+'LK'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_sequence(text)

    def test_sonson_special_can_extend_and_start_a_route(self):
        game=get_game('marvel-vs-capcom-2')
        rules=validate_rules({'true_combo':False,'starters':['2LK'],'custom_moves':[
            {'name':'41236LK','sequence':'41236LK','enabled':True},
            {'name':'41236HK','sequence':'41236HK','enabled':False}]},game)
        actions=game.search_actions(rules)
        opening=continuation_candidates({'steps':(),'notation':''},actions,rules)[0]
        followups=continuation_candidates(opening,actions,rules)
        self.assertTrue(any(move['last']=='41236LK' for move in followups))
        self.assertFalse(any(move['last']=='41236HK' for move in followups))
        rules=validate_rules({**rules,'starters':['41236LK']},game)
        self.assertEqual({move['last'] for move in continuation_candidates({'steps':(),'notation':''},actions,rules)},{'41236LK'})
        with self.assertRaises(ValueError):validate_rules({**rules,'disabled_buttons':['LK']},game)

    def test_compact_starter_notation_and_named_moves(self):
        game=get_game('vampire-savior')
        rules=validate_rules({'custom_moves':[{'name':'My opening','sequence':'LP, N, HP','enabled':True}]},game)
        actions=game.search_actions(rules)
        self.assertEqual(parse_starter('My opening',actions),['My opening'])
        self.assertEqual(parse_sequence('LP+LK'),(Step(1,('LP','LK')),))
        for text in ('2LK2LK','2lk 2lk','c.LK > c.LK','2LK, 2LK'):
            self.assertEqual(parse_starter(text,actions),['c.LK','c.LK'])
        self.assertEqual(parse_starter('5LP236HP',actions),['LP','236HP'])
        self.assertEqual(parse_starter('My opening > 2HP',actions),['My opening','c.HP'])
        for text in ('2LKwat','2LK,,2HP','2LK >',';','2LK'*65):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_starter(text,actions)
        for changes in ({'disabled_buttons':['LK']},{'disabled_actions':['c.LK']},{'depth':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_rules({'starters':['2LK2LK'],**changes},game)

    def test_sequence_starter_forces_prefix_then_allows_followups(self):
        game=get_game('vampire-savior')
        rules=validate_rules({'starters':['2LK2LK'],'max_start_delay':2},game)
        actions=game.search_actions(rules)
        first=continuation_candidates({'steps':(),'notation':''},actions,rules)
        self.assertEqual({c['last'] for c in first},{'c.LK'})
        self.assertEqual({c['delay'] for c in first},{0,1,2})
        second=continuation_candidates(first[0],actions,rules)
        self.assertEqual({c['last'] for c in second},{'c.LK'})
        self.assertTrue(all(c['delay']>=1 for c in second))
        self.assertGreater(len({c['delay'] for c in second}),1)
        self.assertTrue(all(c['action_names']==['c.LK','c.LK'] for c in second))
        following=continuation_candidates(second[0],actions,rules)
        self.assertTrue(any(c['last']=='c.HP' for c in following))

    def test_multiple_starters_include_custom_moves_and_only_restrict_opening(self):
        game=get_game('vampire-savior')
        rules=validate_rules({'starters':['c.LK','c.HP','Opening','c.LK'],'max_start_delay':3,
            'custom_moves':[{'name':'Opening','sequence':'LP, N, HP','enabled':True}]},game)
        self.assertEqual(rules['starters'],['c.LK','c.HP','Opening'])
        self.assertEqual(rules['starter'],'')
        candidates=continuation_candidates({'steps':(),'notation':''},game.search_actions(rules),rules)
        self.assertEqual({c['last'] for c in candidates},set(rules['starters']))
        for starter in rules['starters']:
            openings=[c for c in candidates if c['last']==starter]
            self.assertEqual({c['delay'] for c in openings},set(range(4)))
            parent={**openings[0],'state':{'p1':{'y':40}}}
            followups=continuation_candidates(parent,game.search_actions(rules),rules)
            self.assertTrue(any(c['last'] not in rules['starters'] for c in followups))

    def test_multiple_starter_validation_and_legacy_migration(self):
        game=get_game('vampire-savior')
        for change in ({'starters':'LP'},{'starters':None},{'starters':[None]},
                       {'starters':['']},{'starters':['missing']},
                       {'starters':['LP','c.HP'],'disabled_actions':['LP']},
                       {'starters':['c.LK'],'disabled_buttons':['LK']},
                       {'starters':['236LP'],'groups':['normals']}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_rules(change,game)
        self.assertEqual(validate_rules({},game)['starters'],[])
        migrated=validate_rules({'starter':'c.LK'},game)
        self.assertEqual(migrated['starters'],['c.LK'])
        self.assertEqual(migrated['starter'],'c.LK')

    def test_selected_starter_only_restricts_first_action(self):
        game=get_game('vampire-savior')
        for starter in ('c.LK','Opening'):
            rules=validate_rules({'starter':starter,'max_start_delay':3,
                'custom_moves':[{'name':'Opening','sequence':'LP, N, HP','enabled':True}]},game)
            actions=game.search_actions(rules)
            candidates=continuation_candidates({'steps':(),'notation':''},actions,rules)
            self.assertEqual({c['last'] for c in candidates},{starter})
            self.assertEqual({c['delay'] for c in candidates},set(range(4)))
            parent={**candidates[0],'state':{'p1':{'y':40}}}
            followups=continuation_candidates(parent,actions,rules)
            self.assertTrue(any(c['last']!=starter for c in followups))
        for change in ({'starter':'missing'},{'starter':None},
                       {'starter':'LP','disabled_actions':['LP']},
                       {'starter':'LP','disabled_buttons':['LP']},
                       {'starter':'236LP','groups':['normals']}):
            with self.assertRaises(ValueError): validate_rules(change,game)
        self.assertEqual(validate_rules({},game)['starter'],'')

    def test_demon_sequence_has_distinct_taps(self):
        steps=parse_sequence('LP, N, LP, F, LK, HP')
        self.assertEqual(steps,(Step(1,('LP',)),Step(1),Step(1,('LP',)),Step(1,('F',)),Step(1,('LK',)),Step(1,('HP',))))
        self.assertEqual(parse_sequence('D+F:3, HP:2'),(Step(3,('D','F')),Step(2,('HP',))))

    def test_custom_only_and_individual_move_exclusions(self):
        game=get_game('vampire-savior')
        rules=validate_rules({**DEFAULT_RULES,'groups':[], 'custom_moves':[{'name':'Demon','sequence':'LP, N, LP, F, LK, HP','enabled':True}]},game)
        self.assertEqual([a.name for a in game.search_actions(rules)],['Demon'])
        rules=validate_rules({**DEFAULT_RULES,'disabled_actions':['LP']},game)
        self.assertNotIn('LP',[a.name for a in game.search_actions(rules)])
        rules=validate_rules({**DEFAULT_RULES,'disabled_buttons':['LP'],
                              'custom_moves':[{'name':'LP then HK','sequence':'LP, HK','enabled':True}]},game)
        self.assertTrue(all('LP' not in step.buttons for action in game.search_actions(rules) for step in action.steps))
        self.assertNotIn('LP then HK',[action.name for action in game.search_actions(rules)])

    def test_start_budget_defaults_to_zero_and_bounds_custom_waits(self):
        from combochan.games import Action
        actions=[Action('LP',(Step(1,('LP',)),),'custom'),Action('Wait then HP',(Step(4),Step(1,('HP',))),'custom')]
        parent={'steps':(),'notation':''}
        candidates=continuation_candidates(parent,actions,DEFAULT_RULES)
        self.assertEqual([(c['last'],c['delay']) for c in candidates],[('LP',0)])
        rules={**DEFAULT_RULES,'max_start_delay':5}
        candidates=continuation_candidates(parent,actions,rules)
        self.assertEqual({c['delay'] for c in candidates if c['last']=='LP'},set(range(6)))
        self.assertEqual({c['delay'] for c in candidates if c['last']=='Wait then HP'},{0,1})
        for value in (-1,121,True):
            with self.assertRaises(ValueError):validate_rules({**rules,'max_start_delay':value},get_game('vampire-savior'))

    def test_crouch_chain_preserves_down_and_prioritizes_contact(self):
        game=get_game('vampire-savior')
        parent={'steps':(Step(1,('D','LK')),),'notation':'c.LK','last':'c.LK','contact_delays':[7,8,9]}
        candidates=continuation_candidates(parent,game.actions(['normals']),DEFAULT_RULES)
        self.assertEqual(candidates[0]['last'],'c.MP')
        self.assertEqual(candidates[0]['delay'],7)
        self.assertTrue(any(c['last']=='c.MK' and c['delay']==0 for c in candidates))
        self.assertFalse(any(c['last']=='c.LK' and c['delay']==0 for c in candidates))

    def test_air_heavy_can_restart_ground_chain_with_light(self):
        game=get_game('vampire-savior')
        parent={'steps':(Step(1,('HP',)),),'notation':'HP','last':'HP','state':{'p1':{'y':74}},'landing_delays':[8,9]}
        candidates=continuation_candidates(parent,game.actions(['normals']),DEFAULT_RULES)
        self.assertEqual([c['last'] for c in candidates[:3]],['c.LP','c.LK','c.MP'])
        self.assertEqual(candidates[1]['delay'],8)

    def test_chain_windows_not_buried_under_motion_library(self):
        game=get_game('vampire-savior')
        parent={'steps':(Step(1,('D','LK')),),'notation':'c.LK','last':'c.LK','contact_delays':[5,6,7]}
        candidates=continuation_candidates(parent,game.actions(['normals','motions','movement']),DEFAULT_RULES)
        self.assertTrue(any(c['last']=='c.MK' and c['delay']==6 for c in candidates[:20]))

    def test_custom_command_can_finish_at_contact_window(self):
        from combochan.games import Action
        action=Action('Demon',parse_sequence('LP, N, LP, F, LK, HP'),'custom')
        parent={'steps':(Step(1,('D','HP')),),'notation':'c.HP','last':'c.HP','contact_frames':[15],'contact_delays':[14,15,13]}
        candidates=continuation_candidates(parent,[action],DEFAULT_RULES)
        self.assertEqual(candidates[0]['delay'],10)

    def test_reject_invalid_move_input(self):
        for sequence in ('LP,,HP','L+R','LP:0','LP:241','os.execute(foo)','LP:-1'):
            with self.assertRaises(ValueError):parse_sequence(sequence)

    def test_observed_landing_window_prioritized(self):
        game=get_game('vampire-savior')
        trace=[{'frame':f,'p1':{'y':68 if f<35 else 40}} for f in range(50)]
        landing=game.landing_delays(trace,1,60)
        self.assertEqual(landing,[34,35,33,36,32])
        parent={'steps':(Step(1,('HP',)),),'notation':'HP','landing_delays':landing}
        candidates=continuation_candidates(parent,game.actions(['normals']),DEFAULT_RULES)
        self.assertEqual(candidates[0]['delay'],34)
        self.assertTrue(any(c['delay']==35 and c['last']=='MP' for c in candidates))
        self.assertEqual({c['delay'] for c in candidates[:12]},{34})
        self.assertTrue(all(c['delay']<=60 for c in candidates))

    def test_first_move_can_be_delayed_and_manual_timing_respected(self):
        parent={'steps':(),'notation':''}
        game=get_game('vampire-savior')
        rules={**DEFAULT_RULES,'auto_timing':False,'delays':[0,7,35],'max_start_delay':35}
        candidates=continuation_candidates(parent,game.actions(['normals']),rules)
        self.assertEqual({c['delay'] for c in candidates},set(range(36)))
        self.assertEqual(timing_options({'steps':(Step(1,('LP',)),)},rules),[0,7,35])
        self.assertTrue(any(c['steps'][0]==Step(35) for c in candidates))

    def test_beam_keeps_same_move_with_different_timings(self):
        survivors=[{'last':name,'delay':delay,'score':{'damage':damage},'state':{'p1':{'x':0},'p2':{'x':10}}} for name,delay,damage in [('HP',0,10),('HP',34,10),('MP',0,9),('LP',0,8)]]
        frontier=select_frontier(survivors,3)
        self.assertEqual(len([c for c in frontier if c['last']=='HP']),2)

    def test_extension_room_preserves_lower_damage_openings(self):
        state={'p1':{'x':0},'p2':{'x':10}}
        def route(names,damage,window):
            return {'last':names[-1],'action_names':names,'score':{'damage':damage,'hit_count':len(names)},
                    'state':state,'extension_window':window}
        burst=route(['HP'],80,0)
        light=route(['LP'],5,20)
        light_alt=route(['LP'],6,19)
        kick=route(['LK'],4,18)
        selected=select_frontier([burst,light,light_alt,kick],4)
        self.assertEqual(selected[:2],[light,kick])
        self.assertIn(burst,selected)
        self.assertEqual(select_frontier([burst,light],1),[light])

    def test_unknown_hitstun_does_not_invent_extension_room(self):
        from combochan.dashboard_worker import extension_window
        trace=[{'frame':f,'p2':{'stun1':None,'stun2':None}} for f in range(20)]
        score={'damage_events':[{'frame':3,'damage':5}]}
        self.assertEqual(extension_window(trace,1,score),0)
        for row in trace: row['p2']['stun1']=int(3<=row['frame']<12)
        self.assertEqual(extension_window(trace,1,score),9)
        self.assertEqual(extension_window(trace,10,score),2)


    def test_search_discovers_air_to_ground_route(self):
        class JumpInBridge:
            def __init__(self,*args,**kwargs):pass
            def run(self,trials,speed='turbo'):
                records=[]
                for trial in trials:
                    inputs={};frame=0
                    for step in trial.steps:
                        for _ in range(step.frames):
                            frame+=1;inputs[frame]=step.buttons
                    events={};air_hit=False;ground_hit=False
                    for f,buttons in inputs.items():
                        if 'LP' in buttons and f<10 and not air_hit:events[f]=5;air_hit=True
                        if 'MP' in buttons and 35<=f<=39 and not ground_hit:events[f]=20;ground_hit=True
                    for repetition in range(trial.repeats):
                        trace=[]
                        for f in range(frame+trial.tail+1):
                            damage=sum(d for when,d in events.items() if when<=f)
                            p={'health':288,'recoverable':288,'stocks':2,'meter':0,'x':0,'y':68 if f<35 else 40,'state':512,'facing':0,'stun1':0,'stun2':0}
                            trace.append({'frame':f,'p1':p,'p2':{**p,'x':10,'y':40,'health':288-damage,'stun1':int(damage>0 and f<45)}})
                        records.append({'id':trial.id,'defense':trial.defense,'trace':trace})
                return records,{'job':'synthetic-jump-in'}
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory);(session/'bridge').mkdir();(session/'bridge/root.fs').write_bytes(b'jump')
            script=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            (session/'bridge/ready.json').write_text(json.dumps({'script_content':script.read_bytes().decode('utf-8')}),encoding='utf-8')
            rules={**DEFAULT_RULES,'budget':300,'depth':2,'beam':8,'groups':[], 'custom_moves':[{'name':'Air LP','sequence':'LP','enabled':True},{'name':'Ground MP','sequence':'MP','enabled':True}]}
            events=[]
            with patch('combochan.dashboard_worker.Bridge',JumpInBridge):
                execute({'game':'vampire-savior','session':str(session),'rules':rules,'action':'search','model':'unused'},lambda **e:events.append(e))
            best=events[-1]['result']['best']
            self.assertEqual(best['damage'],25)
            self.assertTrue(best['verified'])
            self.assertIn('Air LP',best['notation']);self.assertIn('Ground MP',best['notation'])
            self.assertTrue(any(not step['buttons'] and step['frames']>16 for step in best['steps']))

if __name__=='__main__':unittest.main()
