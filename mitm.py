import mitmproxy
from mitmproxy import flowfilter
from mitmproxy import proxy, options, ctx
from mitmproxy.tools.dump import DumpMaster
import sched
import time
import json
import copy
import os
import asyncio
import threading


scheduler = sched.scheduler(time.time, time.sleep)

class Score:
    def __init__(self):
        self.point = [0,0,0,0]  # instance variable
        self.ba_kase = ""       #E,S,W,N  49,65,81,97 (0x31, 0x41, 0x51, 0x61)
        self.kyoku = 1           #1,2,3,4
        self.honba = 0           #0,1,2,3...         
    
class RoomInfo:
    East_UID = -1       #position = 0
    South_UID = -1      #position = 1
    West_UID = -1       #position = 2
    North_UID = -1      #position = 3
    Is_3ma = False
    current_ba_kase = "E"
    current_kyoku = 1    
    current_honba = 0
    mid_game = False

def run_scheduler():
    global scheduler
    while True:
        if not scheduler.empty():
            scheduler.run(blocking=False)
        time.sleep(5)
        
class Filter:
    filter: flowfilter.TFilter
    

    def __init__(self):
        print("Starting...")
        self.filter = flowfilter.parse('~s ~u record/get')
        

    def response(self, flow: mitmproxy.http.HTTPFlow) -> None:
        #print("response recieved")
        if flowfilter.match(self.filter, flow):
            #debug
            #print(flow.request.url)
            system_time = int(time.time())
            
            global spectate_mode, score_dict 
            
            if flowfilter.match('~u record/getRoomData', flow):
                #enter room
                
                request_body = json.loads(flow.request.get_text())
                spectate_mode = request_body['isObserve']
                
                if spectate_mode != True:
                    return
                
                print("Enter Spectate Room...")
                
                self.clear_queue()
                time.sleep(1)
                
                global roominfo
                
                room_data_dict = json.loads(flow.response.text)
                
                if (room_data_dict['message'] != 'ok'):
                    print("Err: record/getRoomData message not ok...")
                    return
            
                response_time = room_data_dict['data']['nowTime']  
                delta_time = system_time - response_time   ### the difference between expected and actual, need to add (+) this to the time provided by response
                     
                ##load score
                
                for index, kyoku in enumerate(room_data_dict['data']['handRecord']):
                    global roominfo
                    if index == 0:
                        if len(kyoku['players']) == 3:
                            roominfo.Is_3ma = True
                        elif len(kyoku['players']) == 4:
                            roominfo.Is_3ma = False
                        else:
                            #pass
                            ##assume 4 player game
                            roominfo.Is_3ma = False
                        
                        for player_info in kyoku['players']:
                            if player_info['position'] == 0:
                                roominfo.East_UID = player_info['userId']
                            elif player_info['position'] == 1:
                                roominfo.South_UID = player_info['userId']
                            elif player_info['position'] == 2:
                                roominfo.West_UID = player_info['userId']
                            elif player_info['position'] == 3:
                                roominfo.North_UID = player_info['userId']
                            else:
                                pass ##????
                                
                    agari_event_time = int(kyoku['handEventRecord'][-1]['startTime']/1000)
                    
                    score = Score()
                    
                    if kyoku['handEventRecord'][-1]['eventType'] == 5:
                        data_str = kyoku['handEventRecord'][-1].get('data')
                        data_dict = json.loads(data_str)
                        for index , play_profit in enumerate(data_dict.get("user_profit")):
                            if play_profit['user_id'] == roominfo.East_UID:
                                score.point[0] = play_profit['user_point']
                            elif play_profit['user_id'] == roominfo.South_UID:
                                score.point[1] = play_profit['user_point']
                            elif play_profit['user_id'] == roominfo.West_UID:
                                score.point[2] = play_profit['user_point']
                            elif play_profit['user_id'] == roominfo.North_UID:
                                score.point[3] = play_profit['user_point']
                            else:
                                #print("UID mismatch???")
                                pass                        
                    else:
                        pass
                    ##TODO: ba_kase, honba
                    
                    score.kyoku = kyoku['changCi']
                    score.honba = kyoku['benChangNum']
                    
                    
                    if kyoku['quanFeng']==49:        #0x31
                        score.ba_kase = "E"
                    elif kyoku['quanFeng']==65:      #0x41
                        score.ba_kase = "S"
                    elif kyoku['quanFeng']==81:      #0x51
                        score.ba_kase = "W"
                    elif kyoku['quanFeng']==97:      #0x61
                        score.ba_kase = "N"
                    else:
                        score.ba_kase = "?"
                    
                    try:
                        self.to_queue(agari_event_time+delta_time, score)     #deepcopy just in case :thinking:               
                    except Exception as e:
                        print(e)
                    
                    ### lazy way to kill the records in the previous games, can be better optimized for UX
                    time.sleep(0.1)
                
            
            if flowfilter.match('~u record/getGameData', flow) and spectate_mode:
                #periodic update when in room
                #print(flow.response.text)
                
                game_data_dict = json.loads(flow.response.text)
                
                if game_data_dict['data']['handEventRecord']:
                    #print(len(game_data_dict['data']['handEventRecord']))
                    for record in game_data_dict['data']['handEventRecord']:
                        data_str = record.get('data')
                        data_dict = json.loads(data_str)
                        if (data_dict.get('end_type') != None) and (roominfo.mid_game):
                            #print(int(record['startTime']/1000))     ## epoch time, in second
                            response_time  = game_data_dict['data']['nowTime'] 
                            delta_time = system_time - response_time   ### the difference between expected and actual, need to add (+) this to the time provided by response
                            
                            adjusted_time = int(record['startTime']/1000) + delta_time
                            
                            score = Score()
                            
                            for index , play_profit in enumerate(data_dict.get("user_profit")):
                                if play_profit['user_id'] == roominfo.East_UID:
                                    score.point[0] = play_profit['user_point']
                                elif play_profit['user_id'] == roominfo.South_UID:
                                    score.point[1] = play_profit['user_point']
                                elif play_profit['user_id'] == roominfo.West_UID:
                                    score.point[2] = play_profit['user_point']
                                elif play_profit['user_id'] == roominfo.North_UID:
                                    score.point[3] = play_profit['user_point']
                                else:
                                    pass
                                    #score.point[index] = play_profit['user_point']  ## hopefully this works
                                
                            score.honba = roominfo.current_honba
                            score.ba_kase = roominfo.current_ba_kase
                            score.kyoku = roominfo.current_kyoku
                            roominfo.mid_game = False
                            
                            
                            self.to_queue(adjusted_time,copy.deepcopy(score))
                            
                            ##TODO: ba_kase, honba
                        if (roominfo.mid_game == False) and (data_dict.get('hand_cards') != None):
                            quanFeng = data_dict.get('quan_feng')
                            
                            if quanFeng==49:        #0x31
                                roominfo.current_ba_kase = "E"
                            elif quanFeng==65:      #0x41
                                roominfo.current_ba_kase = "S"
                            elif quanFeng==81:      #0x51
                                roominfo.current_ba_kase = "W"
                            elif quanFeng==97:      #0x61
                                roominfo.current_ba_kase = "N"
                            else:
                                roominfo.current_ba_kase = "?"
                                
                            roominfo.current_honba = data_dict.get('ben_chang_num')
                            roominfo.current_kyoku = data_dict.get('chang_ci')
                                
                            roominfo.mid_game = True
      
        else:
            if (flowfilter.match('~u /lobbys', flow) and spectate_mode):        ## black magic to check exit spec room.
                spectate_mode = False
                self.stop_filter()
                print("Exit Spectate Room... stopping future score update")
                return
            #print(flow.request.url)
    
    def to_queue(self, adjusted_time, score):
        global scheduler
        
        ##debug
        #try:
        #    f = open('log.txt', 'a')
        #    current_time_readable = time.strftime("%H:%M:%S",time.localtime())
        #    if score.honba == 0:
        #        f.write(f'''Receive Time:{current_time_readable}\t{score.ba_kase}-{score.kyoku}  \t[{score.point[0]:>6}|{score.point[1]:>6}|{score.point[2]:>6}|{score.point[3]:>6}] --- {int(adjusted_time)}\n''')
        #    else:
        #        f.write(f'''Receive Time:{current_time_readable}\t{score.ba_kase}-{score.kyoku}-{score.honba}\t[{score.point[0]:>6}|{score.point[1]:>6}|{score.point[2]:>6}|{score.point[3]:>6}] --- {int(adjusted_time)}\n''' )
        #    f.close()
        #except Exception as e:
        #    print("Error in writing to log, ---", e)
        
        adjusted_time_with_delay = int(adjusted_time + 300 + 20)        #### agari effect/count set as 20... shd be fine

        if (adjusted_time_with_delay < int(time.time())):
            self.update_score(score)
        else:
            try:
                scheduler.enterabs(adjusted_time_with_delay,1,self.update_score,kwargs={'score':copy.deepcopy(score)})
            except Exception as e:
                print (e)

        
    def update_score(self,score):

        ##debug
        #print(point)
        
        ##cli
        current_time_readable = time.strftime("%H:%M:%S",time.localtime())
        
        if score.honba == 0:
            print(f'''Update Time:{current_time_readable}\t{score.ba_kase}-{score.kyoku}  \t[{score.point[0]:>6}|{score.point[1]:>6}|{score.point[2]:>6}|{score.point[3]:>6}]''' )
        else:
            print(f'''Update Time:{current_time_readable}\t{score.ba_kase}-{score.kyoku}-{score.honba}\t[{score.point[0]:>6}|{score.point[1]:>6}|{score.point[2]:>6}|{score.point[3]:>6}]''' )
        ###e.g. Update Time: 14:59:29  E-1-1 [ 25000| 25000| 25000| 25000]
        
        ##actual
        ##file.io
        try:
            f_East = open('1_East_Score.txt', 'w+')
            f_East.write(f'''{score.point[0]}''')
            f_East.close()
        except Exception as e:
            print("Error in writing East Score, ---", e)
        
        try:
            f_South = open('2_South_Score.txt', 'w+')
            f_South.write(f'''{score.point[1]}''')
            f_South.close()
        except Exception as e:
            print("Error in writing South Score, ---", e)           
            
        try:
            f_West = open('3_West_Score.txt', 'w+')
            f_West.write(f'''{score.point[2]}''')
            f_West.close()
        except Exception as e:
            print("Error in writing West Score, ---", e)    

        try:
            f_North = open('4_North_Score.txt', 'w+')
            f_North.write(f'''{score.point[3]}''')
            f_North.close()
        except Exception as e:
            print("Error in writing North Score, ---", e)
    

    def clear_queue(self):
        global scheduler
        if (scheduler.empty() != True):
            for event in list(scheduler.queue):
                scheduler.cancel(event)
                
    def stop_filter(self):
        self.clear_queue()
            
def clear_scheduler_queue():
    global scheduler
    if (scheduler.empty() != True):
        for event in list(scheduler.queue):
            scheduler.cancel(event)

addons = [
    Filter()
]

spectate_mode = False
roominfo = RoomInfo()

async def start_proxy():
    opts = options.Options(mode=["local:Mahjong-JP.exe"], ssl_insecure=True)

    master = DumpMaster(opts,
    #    with_termlog=False,
        with_dumper=False,
    )
    master.addons.add(*addons)
    try:
        print("Proxy starting....")
        threading.Thread(target=run_scheduler, daemon=True).start()
        await master.run()
    except KeyboardInterrupt:
        master.shutdown()


if __name__ == "__main__":
    #import platform
    import ctypes
    
    ### Remove comment if you do not mind cmd QuickEdit blocking print and halt program
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), 0x80)
    except Exception:
        pass
    
    try:
        asyncio.run(start_proxy())
    except KeyboardInterrupt:
        #client_websocket.stop_manager()
        clear_scheduler_queue()