import sys
import socket
import select
from threading import Timer
import random
import string
import time

# Settable parameters
MTU = 1200 # Maximum Transmit Unit for this medium (B)
RECV_BUFFER = 2*MTU # Receive buffer size
#BANDWIDTH = 10
PDELAY = 0.1
#status
IDLE = 'I'
BUSY = 'B'

#global variable
m_list=[] #medium list
s_number=0 #socket nimber
name=''
r_list=[] #router list
version=0 #router packet version
s_timer=None #router packet timer
r_link_num=0 #count of router link
destination=''
source=''
send_buffer_list=[] #each destination port and source port has 1 list
send_list=[] #save send list
receive_buffer=[]
received_message=''
max_receive_buffer=10
send_timer=None
read_timer=None
loss_number=[]
retransmit=0

class received_data: #save information about received data
	def __init__(self, TCP, dest, src, message):
		self.TCP=TCP
		self.dest=dest
		self.src=src
		self.message=message

class send_buffer: #each destination port and source port has 1 send buffer
	def __init__(self, data_list, src_port, dest_port, count, destination):
		self.data_list=data_list
		self.ESTRTT=0
		self.lastbytewritten=int(count)+2
		self.src_port=src_port
		self.dest_port=dest_port
		self.lastbytesent=-1
		self.lastbyteacked=-1
		self.destination=destination
		self.RTO_list=[]
		self.duplicated_ack=1
		self.termination=0
		self.advertisedwindow=max_receive_buffer
		self.status=1 #1==slow start, 2=congestion avoidance 3=fast recovery
		self.ssthreshold=10
		self.conwin=1
		self.seqnum=0
		self.acknum=0
		self.persistencetimer=None

	def cal_ESTRTT(self , receive_time, send_time):
		self.ESTRTT=self.ESTRTT*7/8+(receive_time-send_time)/8

	def cal_effectivewin(self):
		temp=self.lastbytesent-self.lastbyteacked
		return min(self.advertisedwindow, self.conwin)-temp

class data: #save information about transmit data
	def __init__(self, message, seqnum):
		self.send_time=0
		self.message=message
		self.TCP=TCP_Header()
		self.seqnum=seqnum
		self.retransmission=0

class TCP_Header: #TCP header
	Source_port='0'*16
	Destination_port='0'*16
	seqnum='0'*32
	acknum='0'*32
	h_len='0101'
	reserved='0'*6
	URG='0'
	ACK='0'
	PSH='0'
	RST='0'
	SYN='0'
	FIN='0'
	window_size='0'*16
	checksum='0'*16
	urgent_pointer='0'*16

	def set(self, tcp):
		self.Source_port=b2int(tcp[0:16])
		self.Destination_port=b2int(tcp[16:32])
		self.seqnum=tcp[32:64]
		self.acknum=tcp[64:96]
		self.h_len=tcp[96:100]
		self.reserved=tcp[100:106]
		self.URG=tcp[106]
		self.ACK=tcp[107]
		self.PSH=tcp[108]
		self.RST=tcp[109]
		self.SYN=tcp[110]
		self.FIN=tcp[111]
		self.window_size=tcp[112:128]
		self.checksum=tcp[128:144]
		self.urgent_pointer=tcp[144:160]

	def getheader(self):
		return int2b(self.Source_port)+int2b(self.Destination_port)+self.seqnum+self.acknum+self.h_len+self.reserved+self.URG+self.ACK+self.PSH+self.RST+self.SYN+self.FIN+self.window_size+self.checksum+self.urgent_pointer

	def printheader(self):
		print('---------------------------')
		print('src port: '+str(self.Source_port)+'	dest port: '+ str(self.Destination_port))
		print('seqnum: '+  str(b2int(self.seqnum))+' acknum: '+  str(b2int(self.acknum)))
		print('ACK: '+ self.ACK+' SYN: '+ self.SYN+ ' FIN: '+ self.FIN + ' window: '+self.window_size)
		print('---------------------------')

class r_table: #routing_table
	name_list=[]
	D_list=[] #distance list
	p_list=[] #predecessor list
	s_list=[] #first send list

	def __init__(self):
		self.name_list=[]
		self.D_list=[]
		self.p_list=[]
		self.s_list=[]

class router: #router information
	name=''
	adj_router=[] #adjacent router
	port=[]
	distance=[]
	version=0
	end_node=[]

	def __init__(self,name):
		self.name=name

	def on(self):
		return '#'+str(self.name)+'&'+str(self.adj_router)+'&'+str(self.port)+'&'+str(self.distance)+'&'+str(self.end_node)+'&'

	def dead(self):
		return '#!'+self.name+'#'

class link: #save information about link(router, end_node)
	port=0
	M_STATUS=IDLE
	BANDWIDTH=0
	s=''
	N_STATUS=IDLE
	t1=None
	collision=0
	BACKOFF=0
	data=''
	router=[]

	def __init__(self, p, s):
		self.port=p
		self.s= s

class r_link: #save information about link(router, router)
	port=0
	BANDWIDTH=0
	s=''
	data=''
	router=''
	r_data=''

	def __init__(self, p, s):
		self.port=p
		self.s= s

me=router(name) #router information about this node
table=r_table()

def router_node(): #when router
	global m_list, s_number, name, me, r_list, s_timer, table, destination, send_timer

	for i in range(r_link_num): #make router information about this node
		me.port.append(m_list[i].port)
		me.distance.append(float(float(MTU/m_list[i].BANDWIDTH)+float(PDELAY)))
		me.adj_router.append(m_list[i].router)
	for i in range(r_link_num,s_number):
		me.end_node=me.end_node+m_list[i].router
	r_list.append(me)
	send_router_packet() #when router is on
	sys.stdout.write('type \'q\' to end this router program'); sys.stdout.flush()

	while 1:
		socket_list = [sys.stdin]
		for i in range(s_number):
			socket_list.append(m_list[i].s)

		# Get the list sockets which are readable
		ready_to_read, ready_to_write, in_error = select.select(socket_list, [], [])

		for sock in ready_to_read:		
			for i in range(0, s_number): #check all socket
				if sock==m_list[i].s:
					# Incoming data packet from medium
					packet = sock.recv(RECV_BUFFER) # Recive a packet
					if not packet == '0'*MTU: # receive start packet
						if packet[0]=='#': #get router_packet
							m_list[i].r_data=packet
							get_router_packet(i)
						else:
							m_list[i].data=packet
							if not m_list[i].data:
								print('\nDisconnected \n')
							else:
								flag2=0
								for a in range(len(r_list)): #find where to transmit
									for b in range(len(r_list[a].end_node)):
										if r_list[a].end_node[b]==m_list[i].data[1]:
											flag2=1
											break
									if flag2==1:
										break
								if a==0:
									b=int(b/2)
									destination=m_list[i].data[1]
									m_list[r_link_num+b].data='!'+m_list[i].data[1:]
									transmit(r_link_num+b,'normal')
								else:
									for j in range(1,len(table.name_list)): # check destination
										if table.name_list[j]==r_list[a].name:
											for k in range(r_link_num):
												if table.s_list[j]==m_list[k].router: #find next destination
													m_list[k].data=m_list[i].data
													destination=m_list[i].data[1]
													m_list[k].data='!'+m_list[i].data[1:]
													transmit(k,'normal') #transmit to destination
			if sock==sys.stdin:
				cmd=sys.stdin.readline()
				if cmd=="q\n": #quit
					s_timer.cancel()
					for i in range(r_link_num): #transmit to adj_router that this router is on
						m_list[i].r_data=me.dead()
						transmit(i, 'r_packet')
						m_list[i].s.close()
					sys.exit()

def check_node(): #check whether router or end_node and set basic information
	global name, me, m_list, s_number, r_link_num
	name=raw_input("input the name of node ")
	me=router(name)
	if name=='A':
		m=connect_to_medium(8121, 'r_link')
		m.router='B'
		m.BANDWIDTH=600
		m_list.append(m)
		m=connect_to_medium(9111, 'link')
		m.router=['a']
		m.BANDWIDTH=3000
		m_list.append(m)
		m=connect_to_medium(9121, 'link')
		m.router=['b']
		m.BANDWIDTH=3000
		m_list.append(m)
		m=connect_to_medium(9132, 'link')
		m.router=['c']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=4
		r_link_num=1
		return router_node()

	elif name=='B':
		m=connect_to_medium(8121, 'r_link')
		m.router='A'
		m.BANDWIDTH=600
		m_list.append(m)
		m=connect_to_medium(8231, 'r_link')
		m.router='C'
		m.BANDWIDTH=600
		m_list.append(m)
		m=connect_to_medium(8244, 'r_link')
		m.router='D'
		m.BANDWIDTH=150
		m_list.append(m)
		m=connect_to_medium(9212, 'link')
		m.router=['d']
		m.BANDWIDTH=1500
		m_list.append(m)
		m=connect_to_medium(9222, 'link')
		m.router=['e']
		m.BANDWIDTH=1500
		m_list.append(m)
		m=connect_to_medium(9232, 'link')
		m.router=['f']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=6
		r_link_num=3
		return router_node()
	elif name=='C':
		m=connect_to_medium(8231, 'r_link')
		m.router='B'
		m.BANDWIDTH=600
		m_list.append(m)
		m=connect_to_medium(8342, 'r_link')
		m.router='D'
		m.BANDWIDTH=300
		m_list.append(m)
		m=connect_to_medium(9311, 'link')
		m.router=['g']
		m.BANDWIDTH=3000
		m_list.append(m)
		m=connect_to_medium(9321, 'link')
		m.router=['h']
		m.BANDWIDTH=3000
		m_list.append(m)
		m=connect_to_medium(9331, 'link')
		m.router=['i']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=5
		r_link_num=2
		return router_node()
	elif name=='D':
		m=connect_to_medium(8244, 'r_link')
		m.router='B'
		m.BANDWIDTH=150
		m_list.append(m)
		m=connect_to_medium(8342, 'r_link')
		m.router='C'
		m.BANDWIDTH=300
		m_list.append(m)
		m=connect_to_medium(9412, 'link')
		m.router=['j']
		m.BANDWIDTH=1500
		m_list.append(m)
		m=connect_to_medium(9422, 'link')
		m.router=['k']
		m.BANDWIDTH=1500
		m_list.append(m)
		m=connect_to_medium(9431, 'link')
		m.router=['l']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=5
		r_link_num=2
		return router_node()
	elif name=='a':
		m=connect_to_medium(9111, 'link')
		m.router=['A']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='b':
		m=connect_to_medium(9121, 'link')
		m.router=['A']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='c':
		m=connect_to_medium(9132, 'link')
		m.router=['A']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='d':
		m=connect_to_medium(9212, 'link')
		m.router=['B']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='e':
		m=connect_to_medium(9222, 'link')
		m.router=['B']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='f':
		m=connect_to_medium(9232, 'link')
		m.router=['B']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='g':
		m=connect_to_medium(9311, 'link')
		m.router=['C']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='h':
		m=connect_to_medium(9321, 'link')
		m.router=['C']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='i':
		m=connect_to_medium(9331, 'link')
		m.router=['C']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='j':
		m=connect_to_medium(9412, 'link')
		m.router=['D']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='k':
		m=connect_to_medium(9422, 'link')
		m.router=['D']
		m.BANDWIDTH=1500
		m_list.append(m)
		s_number=1
		return end_node()
	elif name=='l':
		m=connect_to_medium(9431, 'link')
		m.router=['D']
		m.BANDWIDTH=3000
		m_list.append(m)
		s_number=1
		return end_node()		

def end_node(): #when end_node
	global send_buffer_list, m_list, s_number, name, me, r_list, s_timer, table, destination, source, send_list, received_message, receive_time, send_timer, read_timer, loss_number
	source=me.name
	sys.stdout.write('Type \'t\' for transmitting a packet or type \'q\' to end this program'); sys.stdout.flush()

	while 1:
		socket_list = [sys.stdin]
		for i in range(0, s_number):
			socket_list.append(m_list[i].s)

		# Get the list sockets which are readable
		ready_to_read, ready_to_write, in_error = select.select(socket_list, [], [])

		for sock in ready_to_read:
			for i in range(0, s_number): #check all socket
				if sock==m_list[i].s:
					# Incoming data packet from medium
					packet = sock.recv(RECV_BUFFER) # Recive a packet
					if packet == '0'*MTU: # receive start packet
						m_list[i].M_STATUS=BUSY
						if m_list[i].N_STATUS==BUSY and m_list[i].BACKOFF==0: #collision!!
							send_timer.cancel()
							if not m_list[i].t1==None:
								m_list[i].t1.cancel()
							if len(send_list)>0:
								if not m_list[0].data==send_list[0]:
									send_list.insert(0, m_list[i].data)
							else:
								send_list.insert(0, m_list[i].data)
							m_list[i].collision=m_list[i].collision+1
							if m_list[i].collision>6: # maximum 6
								m_list[i].collision=6
							#print('collision')
							Timer(float(MTU)/m_list[i].BANDWIDTH, change_status, ('3', i)).start()
					else:
						if not packet:
							print('\nDisconnected \n')
						else:
							packet=extract_data(packet)
							if packet[0]=='^':
								m_list[i].M_STATUS=IDLE
								if m_list[i].N_STATUS==BUSY: #after busy medium
									m_list[i].collision=m_list[i].collision+1
									if m_list[i].collision>6: #maximum 6
										m_list[i].collision=6
									interval=float(random.randrange(0,2**(m_list[i].collision+2)))
									backofftime=interval*MTU/m_list[i].BANDWIDTH/5
									if m_list[i].BACKOFF==0: #running transmiit==0
										m_list[i].BACKOFF=1
										if len(send_list)>0:
											if not m_list[0].data==send_list[0]:
												send_list.insert(0, m_list[i].data)
										else:
											send_list.insert(0, m_list[i].data)
										#print('backoff')
										Timer(backofftime, presending, (2,'')).start() # transmit after backoff time
							elif packet[1]==me.name: #normal receive a packet
								receive_time=time.time()
								print('receive time: '+str(receive_time))
								c=0
								#m_list[i].M_STATUS=IDLE
								received_TCP=TCP_Header()
								received_TCP.set(packet[4:164])
								loss_flag=0
								ii=0
								while ii<len(loss_number): #check intentional packet loss
									if b2int(received_TCP.seqnum)==loss_number[ii]:
										loss_flag=1
										loss_number.pop(ii)
										break
									ii=ii+1
								if not loss_flag==1:
									print('receive')
									received_TCP.printheader()
									destination=packet[3]
									received_message=packet[164:]
									#check TCP header
									if received_TCP.SYN=='1':
										acksyn(i, received_TCP)
									elif (received_TCP.ACK=='1') and (received_TCP.FIN=='0'):
										ack(i, received_TCP)
									elif received_TCP.FIN=='0' and received_TCP.ACK=='0' and received_TCP.SYN=='0':
										send_ack(i, received_TCP)
									elif received_TCP.FIN=='1' and received_TCP.ACK=='0':
										ackfin(i, received_TCP)
									elif received_TCP.FIN=='1' and received_TCP.ACK=='1':
										termination(i, received_TCP)

			if sock==sys.stdin:
				cmd=sys.stdin.readline()
				if cmd=="q\n": #quit
					for i in range(s_number): #transmit to adj_router that this router is on
						m_list[i].s.close()
					#read_timer.cancel()
					sys.exit()
				elif cmd=="t\n": #transmit
					src_port=raw_input("input the source port: ")
					dest_port=raw_input("input the destination port: ")
					destination=raw_input("input the destination IP name: ")
					count=raw_input("input the count of message: ")
					temp_data_list=[]
					for k in range(int(count)):
						temp_data=data(generator(), k+2)
						temp_data_list.append(temp_data)

					temp_send_buffer=send_buffer(temp_data_list, src_port, dest_port, count, destination)
					syn(i, temp_send_buffer)
				elif cmd=="n\n": # make packet loss
					loss_count=input('loss count: ')
					for kk in range(loss_count):
						temp_loss=input('input loss seq number: ')
						loss_number.append(temp_loss)

# Connect a node to medium ----- recommand not to modify
def connect_to_medium(port, flag):
	host = '127.0.0.1' # Local host address
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

	s.settimeout(2)
	try:
		s.connect((host, port))
	except:
		print('Unable to connect')
	#sys.exit()

	print('Connected. You can start sending packets')
	if flag=="r_link":
		m=r_link(port, s) #init medium
	else:
		m=link(port,s)
	return m

# Make and transmit a data packet
def transmit (i, flag):
	global N_STATUS, c, M_STATUS, t, t2, BACKOFF, destination, source, data_list, send_timer
	if flag=='r_packet': #router packet transmit
		packet = m_list[i].r_data
		if len(packet) > MTU:
			print('Cannot transmit a packet -----> packet size exceeds MTU')
		else:
			m_list[i].s.send(packet)
	elif flag=='normal':
		packet = m_list[i].data
		#packet = packet + '0'*(MTU-(len(m_list[i].data)))
		if len(packet) > MTU:
			print('Cannot transmit a packet -----> packet size exceeds MTU')
		else:
			Timer(PDELAY, start_pkt, ()).start() #send start packet
			m_list[i].t1=Timer(float(MTU)/m_list[i].BANDWIDTH+PDELAY, normal_pkt, (i, packet))
			m_list[i].t1.start()
			print("transmit a data %s" % (m_list[i].data))

def change_status(flag, i):
	global m_list
	#print('change status')
	if flag == '0': #change node to idle
		m_list[i].M_STATUS=IDLE
		m_list[i].N_STATUS=IDLE
		m_list[i].collision=0
	elif flag=='1': #change medium to idle when collision
		m_list[i].M_STATUS=IDLE
		interval=float(random.randrange(0,2**(m_list[i].collision+2)))
		backofftime=float(interval*MTU/m_list[i].BANDWIDTH/5)
		if m_list[i].BACKOFF==0: #no other trasmit
			m_list[i].BACKOFF=1
			Timer(backofftime, transmit, (i, 1)).start()
	elif flag=='2':
		m_list[i].M_STATUS=IDLE
		m_list[i].N_STATUS=IDLE
		m_list[i].collision=0
		presending(1, 'finished')
	elif flag=='3':
		m_list[i].M_STATUS=IDLE
		interval=float(random.randrange(0,2**(m_list[i].collision+2)))
		backofftime=float(interval*MTU/m_list[i].BANDWIDTH/5)
		if m_list[i].BACKOFF==0: #no other trasmit
			m_list[i].BACKOFF=1
			Timer(backofftime, presending, (2, 'finished')).start()

# Extract data
def extract_data(packet):
	global destination, source
	i=0
	if packet[0]=='#': #extract router packet
		for c in packet[1:-1]:
			if c=='#':
				i=i+2
				break
			else:
				i=i+1
				continue
	else: #extract normal packet
		for c in packet:
			if c == '*':
				break
			else:
				i=i+1
				continue

	data = packet[0:i]
	return data

def generator(): # random packet generator
	#print('generator')
	return ''.join(random.choice(string.ascii_lowercase) for _ in range (16)) #random generate

def send_router_packet():
	global s_number, name, me, r_list, version, s_timer, r_link_num
	trans_data=me.on()+str(version)+'&'+'#'
	for i in range(r_link_num): #transmit to adj_router
		m_list[i].r_data=trans_data
		transmit(i, 'r_packet')
	r_list[0].version=version
	version=(version+1)%10 #version up
	s_timer=Timer(10,send_router_packet) #after 10s restart
	s_timer.start()

def Min(a, b): #check minimum changed or not
	if a<b:
		return False
	else:
		return True

def get_router_packet(i): #when get router_on packet
	global name, s_number, me, r_list, version, r_link_num
	if m_list[i].r_data[1]=='!': #dead router
		temp=len(r_list)
		for j in range(temp):
			if r_list[j].name==m_list[i].r_data[2]: #remove router
				r_list.remove(r_list[j])
				dijkstra()
				for k in range(r_link_num):
					m_list[k].r_data=m_list[i].r_data
					transmit(k, 'r_packet')
				break   
	else: #get router_packet
		r_flag1=0
		r_flag2=0
		#set router information
		splited=m_list[i].r_data.split('&')
		rt=router(splited[0][1])
		rt.port=eval(splited[2])
		rt.adj_router=eval(splited[1])
		rt.distance=eval(splited[3])
		rt.end_node=eval(splited[4])
		rt.version=eval(splited[5])

		for j in range(len(r_list)):
			if(r_list[j].name==rt.name):
				r_flag1=1
				if((r_list[j].version+1)%10==rt.version): #version upgrade
					r_list[j]=rt
					r_flag2=1

		if r_flag1==0: #get new router information
			r_list.append(rt)
			dijkstra()

		if r_flag1==0 or r_flag2==1: #when get new router or new version
			for j in range(r_link_num):
				m_list[j].r_data=m_list[i].r_data
				transmit(j, 'r_packet')

def dijkstra(): #dijkstra algorithm
	global r_list, table
	N=[r_list[0].name] #done list
	min_index=0
	table=r_table()
	for i in range(len(r_list)): #append all router
		table.name_list.append(r_list[i].name)

	for i in range(len(table.name_list)):
		table.D_list.append(1000000) #first set infinity
		table.p_list.append('')
		for j in range(len(r_list[0].adj_router)): #set distance list and p_list
			if table.name_list[i]==r_list[0].adj_router[j]:
				table.D_list[i]=r_list[0].distance[j]
				table.p_list[i]=r_list[0].name
	table.D_list[0]=0

	while(len(table.name_list)>len(N)): # until N is full
		minimum=1000000
		for i in range(len(table.name_list)):
			flag=0
			for j in range(len(N)): #if in the N then, pass
				if table.name_list[i]==N[j]:
					flag=1
			if flag==0:
				if Min(minimum, table.D_list[i]): #find minimum
					min_index=i
					minimum=table.D_list[i]
		N.append(table.name_list[min_index])

		for i in range(len(table.name_list)): #update smallest distance, predecessor
			flag=0
			for j in range(len(N)): #if in the N then, pass
				if table.name_list[i]==N[j]:
					flag=1
			if flag==0:
				for j in range(len(r_list[min_index].adj_router)):
					if table.name_list[i]==r_list[min_index].adj_router[j]:
						if Min(table.D_list[i],table.D_list[min_index]+r_list[min_index].distance[j]):
							table.D_list[i]=table.D_list[min_index]+r_list[min_index].distance[j]
							table.p_list[i]=table.name_list[min_index]
	table.s_list.append('')
	for i in range(1, len(table.name_list)): #find s_list
		predecessor=table.p_list[i]
		flag2=0
		if not predecessor=='':
			while(predecessor!=r_list[0].name):
				for j in range(1, len(table.name_list)):
					if predecessor==table.name_list[j]:
						predecessor=table.p_list[j]
						flag2=1
						break
			if flag2==1:
				table.s_list.append(table.name_list[j])
			else:
				table.s_list.append(table.name_list[i])

	#print('!!!!!!')
	#print(str(table.name_list))
	#print(str(table.p_list))
	#print(str(table.D_list))
	#print(str(table.s_list))
	#print('!!!!!!!')

def int2b(t): #change integer to binary
	return '0'*(16-len("{0:b}".format(int(t))))+"{0:b}".format(int(t))

def b2int(t): #change binary to integer
	return int(t,2)

def syn(i, buff): #send syn packet
	global m_list, destination, source, send_buffer_list, send_list
	syn_header=TCP_Header()
	syn_header.Source_port=buff.src_port
	syn_header.Destination_port=buff.dest_port
	syn_header.SYN='1'
	syn_header.seqnum='0'*32
	packet='^'+buff.destination+'^'+source+syn_header.getheader()
	temp_data=data('', 0)
	temp_data.TCP=syn_header
	send_list.append(packet)
	buff.data_list.insert(0, temp_data)
	send_buffer_list.append(buff)
	presending(0, packet)


def acksyn(i, received_TCP): #when syn packet comes, make acksyn to transmit
	global data_list, destination, m_list, source, send_buffer_list, send_list, receive_buffer, receive_time
	ack_header=TCP_Header()
	ack_header.ACK='1'
	ack_header.Destination_port=str(received_TCP.Source_port)
	ack_header.Source_port=str(received_TCP.Destination_port)
	temp=b2int(received_TCP.seqnum)+1
	temp=str(temp)
	ack_header.acknum='0'*(32-len(temp))+temp
	ack_header.window_size=int2b(max_receive_buffer-len(receive_buffer))

	if received_TCP.ACK=='0': #receive first syn // receiver side
		ack_header.SYN='1'
		ack_header.seqnum='0'*32
		temp_data=data('', 0)
		temp_data.TCP=ack_header
		temp_data_list=[temp_data]
		temp_send_buffer=send_buffer(temp_data_list, ack_header.Source_port, ack_header.Destination_port, 0, destination)
		send_buffer_list.append(temp_send_buffer)
		packet='^'+destination+'^'+source+ack_header.getheader()
		send_list.append(packet)
		presending(0, packet)
	else: #receive second syn //sender side
		ack_header.SYN='0'
		temp=b2int(received_TCP.seqnum)+1
		temp=str(temp)
		ack_header.seqnum='0'*(32-len(temp))+temp
		packet='^'+destination+'^'+source+ack_header.getheader()
		send_list.append(packet)
		for j in range(len(send_buffer_list)):
			if (send_buffer_list[j].src_port==ack_header.Source_port) and (send_buffer_list[j].dest_port==ack_header.Destination_port):
				send_buffer_list[j].ESTRTT=receive_time-send_buffer_list[j].data_list[0].send_time
				send_buffer_list[j].RTO_list[0].cancel()
				print('##'+ str(send_buffer_list[j].ESTRTT))
				send_buffer_list[j].lastbyteacked=send_buffer_list[j].lastbyteacked+1
				send_buffer_list[j].acknum=send_buffer_list[j].acknum+1
				send_buffer_list[j].advertisedwindow=b2int(received_TCP.window_size)
				send_buffer_list[j].seqnum=send_buffer_list[j].seqnum+1
				presending(0, packet)
				Timer(float(MTU)/m_list[i].BANDWIDTH+PDELAY+0.1, back2back, (i, j)).start()
				break

def back2back(i, idx): #make data and put to the send_list
	global m_list, source, send_buffer_list, send_list
	temp_TCP=TCP_Header()
	temp_TCP.Source_port=send_buffer_list[idx].src_port
	temp_TCP.Destination_port=send_buffer_list[idx].dest_port
	send_buffer_list[idx].seqnum=send_buffer_list[idx].seqnum+1
	seqnum=int2b(send_buffer_list[idx].seqnum)
	temp_TCP.seqnum='0'*(32-len(seqnum))+seqnum
	acknum=int2b(send_buffer_list[idx].acknum)
	temp_TCP.acknum='0'*(32-len(acknum))+acknum
	send_buffer_list[idx].data_list[send_buffer_list[idx].seqnum-1].TCP=temp_TCP
	packet='^'+send_buffer_list[idx].destination+'^'+source+temp_TCP.getheader()+send_buffer_list[idx].data_list[send_buffer_list[idx].seqnum-1].message
	send_list.append(packet)

	if send_buffer_list[idx].lastbytewritten-1>send_buffer_list[idx].seqnum:
		back2back(i, idx)
	else:
		presending(0, packet)


def ack(i, received_TCP): #when get ack packet
	global send_buffer_list, m_list, send_list, source, receive_time
	flag=0
	for j in range(len(send_buffer_list)):
		if (send_buffer_list[j].src_port==str(received_TCP.Destination_port)) and (send_buffer_list[j].dest_port==str(received_TCP.Source_port)):
			if not send_buffer_list[j].lastbytewritten==2:
				flag=1
			break
	send_buffer_list[j].advertisedwindow=b2int(received_TCP.window_size)
	received_acknum=b2int(received_TCP.acknum)
	send_buffer_list[j].acknum=send_buffer_list[j].acknum+1
	if flag==1:
		k=0
		while k<received_acknum-1:
			if send_buffer_list[j].RTO_list[k]!=None:
				send_buffer_list[j].RTO_list[k].cancel()
			k=k+1
		if(received_acknum>send_buffer_list[j].lastbyteacked+2):

			for l in range(len(send_buffer_list[j].data_list)):
				if send_buffer_list[j].data_list[l].retransmission>0:
					send_buffer_list[j].data_list[l].retransmission=0
					break
				if received_acknum-1==send_buffer_list[j].data_list[l].seqnum:
					send_buffer_list[j].cal_ESTRTT(receive_time, send_buffer_list[j].data_list[l].send_time)
					break

			send_buffer_list[j].lastbyteacked=received_acknum-2
			if send_buffer_list[j].status==3:
				send_buffer_list[j].conwin=send_buffer_list[j].ssthreshold
				send_buffer_list[j].status=2
			elif send_buffer_list[j].status==1:
				send_buffer_list[j].conwin=send_buffer_list[j].conwin+1
				if  send_buffer_list[j].conwin>=send_buffer_list[j].ssthreshold:
					send_buffer_list[j].status=2
			elif send_buffer_list[j].status==2:
				send_buffer_list[j].conwin=send_buffer_list[j].conwin+float(1)/int(send_buffer_list[j].conwin)
			if send_buffer_list[j].lastbytewritten-2==send_buffer_list[j].lastbyteacked:
				fin(i, j)
			else:
				presending(1,'')
		else:
			if send_buffer_list[j].status==3:
				send_buffer_list[j].conwin=send_buffer_list[j].conwin+1
				presending(3, '')
			else:
				send_buffer_list[j].duplicated_ack=send_buffer_list[j].duplicated_ack+1
				if send_buffer_list[j].duplicated_ack==3:
					send_buffer_list[j].status=3
					send_buffer_list[j].data_list[k].TCP.printheader()
					packet='^'+send_buffer_list[j].destination+'^'+source+send_buffer_list[j].data_list[k].TCP.getheader()+send_buffer_list[j].data_list[k].message
					retransmission(packet, 1)
					send_buffer_list[j].duplicated_ack=1
	else:
		send_buffer_list[j].ESTRTT=receive_time-send_buffer_list[j].data_list[0].send_time
		send_buffer_list[j].RTO_list[0].cancel()
		send_buffer_list[j].acknum=send_buffer_list[j].acknum+1
		send_buffer_list[j].lastbyteacked=send_buffer_list[j].lastbyteacked+1

def send_ack(i, received_TCP): #when get data, make ack packet to transmit
	global send_buffer_list, m_list, destination, source, send_list, receive_buffer, received_message
	flag=0
	for j in range(len(send_buffer_list)):
		if (send_buffer_list[j].src_port==str(received_TCP.Destination_port)) and (send_buffer_list[j].dest_port==str(received_TCP.Source_port)):
			if send_buffer_list[j].lastbytewritten==2:
				flag=1
			break
	if flag==1:
		temp_TCP=TCP_Header()
		temp_TCP.ACK='1'
		temp_TCP.Source_port=received_TCP.Destination_port
		temp_TCP.Destination_port=received_TCP.Source_port
		r_data=received_data(received_TCP, source, destination, received_message)
		if len(receive_buffer)>=max_receive_buffer:
			print('packet loss')
		else:
			receive_buffer.append(r_data)
		if send_buffer_list[j].acknum==b2int(received_TCP.seqnum):
			send_buffer_list[j].acknum=send_buffer_list[j].acknum+1
			receive_buffer.pop()
			print("port:" + str(received_TCP.Destination_port) +" read "+ received_message+ " from port:" +str(received_TCP.Source_port))
			k=0
			while k<len(receive_buffer):
				src_port=receive_buffer[k].TCP.Source_port
				dest_port=receive_buffer[k].TCP.Destination_port
				message=receive_buffer[k].message
				if str(dest_port)==send_buffer_list[j].src_port and str(src_port)==send_buffer_list[j].dest_port and b2int(receive_buffer[k].TCP.seqnum)==send_buffer_list[j].acknum:
					send_buffer_list[j].acknum=send_buffer_list[j].acknum+1
					receive_buffer.pop(k)
					print("port:" + str(int(dest_port)) +" read "+ message+ " from port:" +str(int(src_port)))
					k=-1
				k=k+1

		acknum=int2b(send_buffer_list[j].acknum)
		temp_TCP.acknum='0'*(32-len(acknum))+acknum
		send_buffer_list[j].seqnum=send_buffer_list[j].seqnum+1
		seqnum=int2b(send_buffer_list[j].seqnum)		
		temp_TCP.seqnum='0'*(32-len(seqnum))+seqnum
		temp_TCP.window_size=int2b(max_receive_buffer-len(receive_buffer))
		packet='^'+destination+'^'+source+temp_TCP.getheader()
		send_list.append(packet)
		presending(0, packet)	

def fin(i, idx): #make fin packet to send
	global m_list, source, send_buffer_list, send_list
	temp_TCP=TCP_Header()
	temp_TCP.Source_port=send_buffer_list[idx].src_port
	temp_TCP.Destination_port=send_buffer_list[idx].dest_port
	temp_TCP.FIN='1'
	acknum=int2b(send_buffer_list[idx].acknum)
	temp_TCP.acknum='0'*(32-len(acknum))+acknum
	send_buffer_list[idx].seqnum=send_buffer_list[idx].seqnum+1
	seqnum=int2b(send_buffer_list[idx].seqnum)		
	temp_TCP.seqnum='0'*(32-len(seqnum))+seqnum
	packet='^'+send_buffer_list[idx].destination+'^'+source+temp_TCP.getheader()
	temp_data=data('', b2int(seqnum))
	temp_data.TCP=temp_TCP
	send_list.append(packet)
	send_buffer_list[idx].data_list.append(temp_data)
	presending(0, packet)

def ackfin(i, received_TCP): #when get fin packet
	global send_buffer_list, m_list, destination, source, send_list
	flag=0
	temp_TCP=TCP_Header()
	temp_TCP.ACK='1'
	temp_TCP.FIN='1'
	temp_TCP.Source_port=received_TCP.Destination_port
	temp_TCP.Destination_port=received_TCP.Source_port
	for j in range(len(send_buffer_list)):
		if (send_buffer_list[j].src_port==str(received_TCP.Destination_port)) and (send_buffer_list[j].dest_port==str(received_TCP.Source_port)):
			if send_buffer_list[j].lastbytewritten==2:
				flag=1
			break
	if send_buffer_list[j].acknum==b2int(received_TCP.seqnum):
		send_buffer_list[j].acknum=b2int(received_TCP.seqnum)+1
	acknum=int2b(send_buffer_list[j].acknum)
	temp_TCP.acknum='0'*(32-len(acknum))+acknum
	send_buffer_list[j].seqnum=send_buffer_list[j].seqnum+1
	seqnum=int2b(send_buffer_list[j].seqnum)		
	temp_TCP.seqnum='0'*(32-len(seqnum))+seqnum
	packet='^'+destination+'^'+source+temp_TCP.getheader()
	send_list.append(packet)
	presending(0,packet)
	if flag==1:
		fin(i,j)
	send_buffer_list[j].termination=send_buffer_list[j].termination+1
	if send_buffer_list[j].termination==2:
				send_buffer_list.pop(j)

def termination(i, received_TCP): #when get ackfin packet
	global send_buffer_list, m_list, destination, source, send_list
	flag=0
	for j in range(len(send_buffer_list)):
		if (send_buffer_list[j].src_port==str(received_TCP.Destination_port)) and (send_buffer_list[j].dest_port==str(received_TCP.Source_port)):
			send_buffer_list[j].RTO_list[send_buffer_list[j].lastbytewritten-1].cancel()
			send_buffer_list[j].termination=send_buffer_list[j].termination+1
			if send_buffer_list[j].termination==2:
				send_buffer_list.pop(j)
			break


def presending(flag, packet): #check many condition before transmit packet
	global send_list, m_list, send_buffer_list, receive_buffer, send_timer, retransmit
	flag2=0
	flag3=0

	if len(send_list)>0:
		m_list[0].N_STATUS=BUSY
		if not m_list[0].M_STATUS==BUSY:
			if send_timer==None:
				flag2=1
			elif not send_timer.is_alive():
				flag2=1
			elif packet=='finished':
				flag2=1
			if flag2==1:
				m_list[0].data=send_list.pop(0)
				temp_TCP=TCP_Header()
				temp_TCP.set(m_list[0].data[4:164])
				for j in range(len(send_buffer_list)):
					if (int(send_buffer_list[j].src_port)==temp_TCP.Source_port) and (int(send_buffer_list[j].dest_port)==temp_TCP.Destination_port):
						if send_buffer_list[j].cal_effectivewin()<1 and retransmit==0:
							persistence(j)
							send_list.insert(0, m_list[0].data)
							return
						for k in range(len(send_buffer_list[j].data_list)):
							if b2int(temp_TCP.seqnum)==send_buffer_list[j].data_list[k].seqnum:	
								temp_TCP.acknum=int2b(send_buffer_list[j].acknum)
								temp_TCP.acknum='0'*(32-len(temp_TCP.acknum))+temp_TCP.acknum
								m_list[0].data=m_list[0].data[:68]+temp_TCP.acknum+m_list[0].data[100:]
								if not ((temp_TCP.SYN=='0' and temp_TCP.ACK=='1' and temp_TCP.FIN=='0') or(temp_TCP.FIN=='1' and temp_TCP.ACK=='1')):
									send_buffer_list[j].lastbytesent=send_buffer_list[j].lastbytesent+1
									if retransmit>0:
										send_buffer_list[j].lastbytesent=send_buffer_list[j].lastbytesent-1
										retransmit=retransmit-1
										send_buffer_list[j].RTO_list.pop(k)
									if not flag==2:
										if temp_TCP.SYN=='1':
											send_buffer_list[j].RTO_list.insert(k, Timer(30, retransmission, (m_list[0].data, 0)))
											send_buffer_list[j].RTO_list[k].start()
										else:
											send_buffer_list[j].RTO_list.insert(k,Timer(2*send_buffer_list[j].ESTRTT*pow(2,send_buffer_list[j].data_list[k].retransmission), retransmission, (m_list[0].data, 0)))
											send_buffer_list[j].RTO_list[k].start()
								break
						break
				print('!!!!!transmit!!!!!')
				temp_TCP.printheader()
				m_list[0].BACKOFF=0 #run only 1(this) transmit
				send_buffer_list[j].data_list[k].send_time=time.time()
				print(send_buffer_list[j].data_list[k].send_time)
				m_list[0].M_STATUS=BUSY
				Timer(PDELAY, start_pkt, ()).start() #send start packet
				send_timer=Timer(float(MTU)/m_list[0].BANDWIDTH+PDELAY, forward_pkt, (0, ''))
				send_timer.start()

def retransmission(packet, flag): #when retranmsission situation comes
	global send_buffer_list, send_list, source, retransmit
	#print('!!!!!!!!!!!!retransmission!!!!!!!!!!!!!!!!')
	flag2=0
	temp_TCP=TCP_Header()
	temp_TCP.set(packet[4:164])
	for j in range(len(send_buffer_list)):
		if (int(send_buffer_list[j].src_port)==temp_TCP.Source_port) and (int(send_buffer_list[j].dest_port)==temp_TCP.Destination_port):
			for k in range(len(send_buffer_list[j].data_list)):
				if b2int(temp_TCP.seqnum)==send_buffer_list[j].data_list[k].seqnum:
					send_buffer_list[j].data_list[k].retransmission=send_buffer_list[j].data_list[k].retransmission+1
					flag2=1	
					break
			if flag2==1:
				break
	for kk in range(k+1,len(send_buffer_list[j].RTO_list)):
		send_buffer_list[j].RTO_list[kk].cancel()
		temp_packet='^'+send_buffer_list[j].destination+'^'+source+send_buffer_list[j].data_list[kk].TCP.getheader()+send_buffer_list[j].data_list[kk].message
		send_buffer_list[j].RTO_list[kk]=Timer(2*send_buffer_list[j].ESTRTT*pow(2,send_buffer_list[j].data_list[k].retransmission)+(kk-k), retransmission, (temp_packet, 0))
		send_buffer_list[j].RTO_list[kk].start()

	send_buffer_list[j].ssthreshold=int(send_buffer_list[j].conwin)/2
	if send_buffer_list[j].ssthreshold<=0:
		send_buffer_list[j].ssthreshold=1
	if flag==0: #timeout
		send_buffer_list[j].conwin=1
		send_buffer_list[j].staus=1
	elif flag==1: #dupicatedack
		send_buffer_list[j].RTO_list[k].cancel()
		send_buffer_list[j].conwin=send_buffer_list[j].ssthreshold+2
		send_buffer_list[j].status=3
	if len(send_list)>0:
		if not packet==send_list[0]:
			send_list.insert(retransmit, packet)
		else:
			send_list.insert(retransmit, packet)
	retransmit=retransmit+1
	presending(3, packet)

def persistence(j): #when advertisedwindow=0
	global m_list, send_buffer_list, source, receive_buffer
	send_buffer_list[j].advertisedwindow=max_receive_buffer-len(receive_buffer)
	if send_buffer_list[j].advertisedwindow==0:
		print('persistence!!!!!!!!!!!!!!!!!!!!')
		send_buffer_list[j].dest_port
		persistence_TCP=TCP_Header()
		persistence_TCP.seqnum='1'*32
		persistence_TCP.acknum='1'*32
		persistence_TCP.Source_port=send_buffer_list[j].src_port
		persistence_TCP.Destination_port=send_buffer_list[j].dest_port
		probe='^'+destination+'^'+source+persistence_TCP.getheader()
		m_list[0].N_STATUS=BUSY
		m_list[0].BACKOFF=0 #run only 1(this) transmit
		
		m_list[0].s.send(probe)
		m_list[0].M_STATUS=BUSY
		m_list[0].t1=Timer(float(MTU)/m_list[0].BANDWIDTH+PDELAY, change_status, ('2', 0)) # change node status to idle
		m_list[0].t1.start()

		send_buffer_list[j].persistencetimer=Timer(2*send_buffer_list[j].ESTRTT*pow(2,send_buffer_list[j].data_list[k].retransmission), persistence)

def forward_pkt(i, a): #just send packet
	global m_list
	if len(m_list[i].data)!=164:
		m_list[i].data=m_list[i].data+'*'*(MTU-len(m_list[i].data))
	m_list[i].s.send(m_list[i].data)
	change_status('2', 0)# change node status to idle

def start_pkt(): #send start packet
	global m_list
	m_list[0].s.send('0'*MTU)

def normal_pkt(i, a): #send packet in router
	global m_list
	m_list[i].s.send(a)

if __name__ == "__main__":
	 sys.exit(check_node())
