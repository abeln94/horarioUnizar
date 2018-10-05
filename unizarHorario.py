from __future__ import print_function
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
import sys

#PARAMETERS
COMMENT = '#'
CATEGORY = '>'
CATEGORIES = {
	'title': 'TITLE',
	'year': 'YEAR',
	'semester': 'SEMESTER',
	'subjects': 'SUBJECTS',
	'timetable': 'TIMETABLE',
}
SEPARATOR = ';'
DESCRIPTION = "Horarios personales de las asignaturas en Unizar. Creado con la herramienta de Abel Naya."
BATCHMAX = 100

CALENDARS = {
	'days_a' : 'eina.unizar.es_hlti3ac2pou7knidr6e6267g4s@group.calendar.google.com',
	'days_b' : 'eina.unizar.es_ri3mten96cc0s8am0hm080bi94@group.calendar.google.com',
	'holidays' : 'eina.unizar.es_nvgat6f556c48fmtk7llb5i5l0@group.calendar.google.com',
	'exams' : 'eina.unizar.es_8g43cd660rntvu09n32g4hsonk@group.calendar.google.com',
	'evaluation' : 'eina.unizar.es_9vuatq1d533o3aoknsej9vbiv8@group.calendar.google.com',
}

EVENTS = {
	1 : {
		'start' : 'Comienzo clases 1er Semestre',
		'end' : 'Final clases 1er Semestre',
	},
	2 : {
		'start' : 'Comienzo clases 2º Semestre',
		'end' : 'Final clases 2º Semestre',
	},
}


# If modifying these scopes, delete the file token.json.
SCOPES = 'https://www.googleapis.com/auth/calendar'


# Custom Class to handle Date/Time Objects
class MyDate:
	def __init__(self, year=None, string=None, _datetime=None):
		if year is not None:
			self.datetime = datetime(year, 7, 1)
		if string is not None:
			self.datetime = datetime.strptime(string, '%Y-%m-%d')
		if _datetime is not None:
			self.datetime = _datetime

	def toString(self, includeTimezone=True):
		return self.datetime.isoformat() + ('Z' if includeTimezone else '') # 'Z' indicates UTC time
		
	def addDay(self):
		return MyDate(_datetime=self.datetime + timedelta(days=1))
		
	def addSecond(self):
		return MyDate(_datetime=self.datetime + timedelta(seconds=1))
		
	def substractDay(self):
		return MyDate(_datetime=self.datetime - timedelta(days=1))
		
	def isWeekend(self):
		return self.datetime.weekday() >= 5
		
	def getWeekday(self):
		return ['l','m','x','j','v'][self.datetime.weekday()]
		
	def isNot(self, other):
		return self.datetime != other.datetime

	def setTime(self, time):
		return MyDate(_datetime=datetime.combine(self.datetime, time))

	#hashable object
	def __eq__(self, other):
		return self.toString(False) == other.toString(False)
	def __hash__(self):
			return hash(self.toString(False))
		
		
# utility class to execute request in batches
class BatchService:
	def __init__(self, service):
		self.service = service
		self.elements = 0
		self.batch = None
		
	def add(self, element):
		if self.elements == 0:
			self.batch = self.service.new_batch_http_request()
			
		self.batch.add(element)
		self.elements += 1
		
		if self.elements >= BATCHMAX:
			self.execute()
			
	def execute(self):
		if self.batch is not None:
			self.batch.execute()
			self.batch = None
			self.elements = 0
		
# runs a petition and returns ALL 'items' (multiple petitions may be sent). Using YIELD
def getAllItems(function, **params):
	nextPageToken = None
	while nextPageToken != '_':
		result = function(pageToken=nextPageToken, **params).execute()
		nextPageToken = result.get('nextPageToken', '_')
		for item in result.get('items',[]):
			yield item
			
#######################################

# Returns the list of non-holiday days and its type
def getDays(service, startDay, endDay):
	days = {}
	
	# first, all non-weekend days are normal and unespecified
	day = startDay.substractDay()
	while day.isNot(endDay):
		day = day.addDay()
		if day.isWeekend():
			continue
		days[day] = (day.getWeekday(), 'x')
		
	# then remove holidays
	events = getAllItems(service.events().list,
		calendarId=CALENDARS['holidays'],
		timeMin=startDay.toString(),
		timeMax=endDay.addSecond().toString(),
		singleEvents=True,
	)
	
	for event in events:
		eventIni = MyDate(string=event['start']['date'])
		eventEnd = MyDate(string=event['end']['date']).substractDay()
		day = eventIni.substractDay()
		while day.isNot(eventEnd):
			day = day.addDay()
			if day in days:
				del days[day]
			
	# finally update weekday and set A, B 
	for calendar in ['days_a','days_b']:
		events = getAllItems(service.events().list,
			calendarId=CALENDARS[calendar],
			timeMin=startDay.toString(),
			timeMax=endDay.addSecond().toString(),
			singleEvents=True,
		)
		for event in events:
			date = MyDate(string=event['start']['date'])
			unformat = event['summary'].lower()
			if unformat.startswith('horario'):  # special cases: not a, nor b, but different weekday
				days[date] = ({'lunes':'l','martes':'m','miércoles':'x','miercoles':'x','jueves':'j','viernes':'v'}[unformat.split()[1]], 'x')
			else:
				days[date] = (unformat[0], unformat[1])
	
	print("[INFO] Days parsed correctly")
	return days
	
# create all the events
def createEvents(service, data, days, calendarId):
	
	# batch execution
	batchService = BatchService(service)
	for day in sorted(days, key= lambda v: v.toString()):
		daytype = days[day]
			
		print("[INFO]", day.toString(), "es", daytype)
		
		for event in data['timetable'][daytype[0]]:
			if daytype[1] not in event[0]:
				continue
				
			subject = data['subjects'][event[3]]
			print("[INFO] Adding event ", event, subject)
			batchService.add(service.events().insert(calendarId=calendarId, body={
				'summary': subject[0],
				'description': subject[1],
				'start': {'dateTime': day.setTime(event[1]).toString(False), 'timeZone':'Europe/Madrid' },
				'end': {'dateTime': day.setTime(event[2]).toString(False), 'timeZone':'Europe/Madrid' },
			}))
			
	batchService.execute()
	
# Returns the Period (start end) dates
def getPeriod(service, year, semester):
	startDay = None
	endDay = None
	
	events = getAllItems(service.events().list,
		calendarId=CALENDARS['evaluation'],
		timeMin=MyDate(year=year).toString(),
		timeMax=MyDate(year=year+1).toString(),
	)
	
	#find the start/end events
	for event in events:
		if event['summary']==EVENTS[semester]['start']:
			startDay = MyDate(string=event['start']['date'])
		if event['summary']==EVENTS[semester]['end']:
			endDay = MyDate(string=event['start']['date'])
	
	print("[INFO] startDay=",startDay.toString()," endDay=",endDay.toString())
	
	return (startDay, endDay)
	
	
# Returns the calendarId of a new calendar where to insert the events
# If a previously created calendar is found, events in the range are deleted first
def getCalendarId(service, title, startDay, endDay):
	calendarId = None
	
	calendars = getAllItems(service.calendarList().list)
	#search existing calendar
	for calendar in calendars:
		if calendar.get('summary',"") == title:
			calendarId = calendar['id']
			
			#remove	all events
			batchService = BatchService(service)
			items = getAllItems(service.events().list,
				calendarId=calendarId,
				timeMin=startDay.toString(),
				timeMax=endDay.addSecond().toString(),
			)
			for event in items:
				batchService.add(service.events().delete(
					calendarId=calendarId,
					eventId=event['id'],
				))
			batchService.execute()
			
			print("[INFO] calendar found, events cleared")
			break
			
	if calendarId == None:
		#create calendar
		calendarId = service.calendars().insert(body={
			'summary': title,
			'description': DESCRIPTION,
			'timeZone': 'Europe/Madrid',
		}).execute()['id']
		print("[INFO] calendar created")
	
	return calendarId
	
	
	
# Adds the official calendars to the account, if they are not found
def addCalendars(service):
	ids = [id for id in CALENDARS.values()]
	
	calendars = getAllItems(service.calendarList().list)
	#search existing calendar
	for calendar in calendars:
		if calendar['id'] in ids:
			ids.remove(calendar['id'])

	batchService = BatchService(service)
	for id in ids:
		batchService.add( service.calendarList().insert(body={
			'id': id,
		}))
	batchService.execute()
	
	
	
# parse the file and load the raw configuration
def loadConfig(filename):
	configuration = {}
	
	#parse file
	category = None
	for line in open(filename, 'r', encoding='utf-8'):
		#remove comments and spaces
		if COMMENT in line:
			line = line[0:line.find(COMMENT)]
		line = line.strip()
		
		#change category
		if line.startswith(CATEGORY):
			category = line[len(CATEGORY):]
			continue
			
		#skip line
		if len(line) == 0 or category == None:
			continue
	
		# append line to category
		configuration.setdefault(category,[]).append(line)
	
	print("[INFO] configuration loaded")
	return configuration
	
	
	
# parses the configuration introduced. If invalid prints the reason/reasons and returns None
def parseConfig(configuration):
	data = {}
	valid = True
	
	# check if all categories are present before parsing each one
	for category_name, category_label in CATEGORIES.items():
		if category_label not in configuration:
			print("Missing category >"+category_label)
			valid = False
		else:
			configuration[category_name] = configuration[category_label]
			
	#stops if a category is missing, otherwise check them 
	if not valid:
		return
			
			
	#category title
	if len(configuration['title']) > 1:
		print("[WARNING] more than one title found, using first only \""+configuration['title'][0]+"\"")
	data['title'] = configuration['title'][0]
			
	#category year
	if len(configuration['year']) > 1:
		print("[WARNING] more than one year found, using first only \""+configuration['year'][0]+"\"")
	try:
		data['year'] = int(configuration['year'][0])
	except ValueError:
		print("Invalid year found")
		valid = False
	
	#category semester
	if len(configuration['semester']) > 1:
		print("[WARNING] more than one semester found, using first only \""+configuration['semester'][0]+"\"")
	try:
		data['semester'] = {'1':1,'2':2}[configuration['semester'][0]]
	except KeyError:
		print("Invalid semester found, can be only 1 or 2")
		valid = False
		
	#category subjects
	data['subjects'] = {}
	for v in configuration['subjects']:
		values = v.split(SEPARATOR)
		#check length
		if len(values) != 3:
			print("Invalid subject, must have 3 components \""+v+"\"")
			valid = False
			continue
		data['subjects'][values[0].lower()] = values[1:3]
		
	#category timetable
	data['timetable'] = {'l':[],'m':[],'x':[],'j':[],'v':[]}
	for v in configuration['timetable']:
		values = [vv.lower() for vv in v.split(SEPARATOR)]
		#check length
		if len(values) != 5:
			print("Invalid timetable entry, must have 5 components \""+v+"\"")
			valid = False
			continue
		#check day
		if values[0] not in 'lmxjv':
			print("Invalid timetable entry, invalid day (not 'l','m','x','j' or 'v') \""+v+"\"")
			valid = False
		#check daytype
		for d in values[1]:
			if d not in 'abx':
				print("Invalid timetable entry, invalid daytype element (not 'a' nor 'b' nor 'x')\""+v+"\"")
				valid = False
		#check times
		for i,s in [(2,'startTime'),(3,'endTime')]:
			try:
				values[i] = datetime.strptime(values[i],'%H:%M').time()
			except ValueError:
				print("Invalid timetable entry, invalid "+s+" (not HH:MM) \""+v+"\"")
				valid = False
		#check subject
		if values[4] not in data['subjects']:
			print("Invalid timetable entry, subject not found \""+v+"\"")
			valid = False
			
		#append entry
		if valid:
			data['timetable'][values[0]].append(values[1:])
		
	
	if valid:
		print("[INFO] configuration valid")
		return data
			
			

# returns the google calendar service, example code
def getService():
	store = file.Storage('token.json')
	creds = store.get()
	if not creds or creds.invalid:
			flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
			creds = tools.run_flow(flow, store)
	return build('calendar', 'v3', http=creds.authorize(Http()))
	
	
####################################################


def main(filename):
	
	configuration = loadConfig(filename)
	data = parseConfig(configuration)
	if data==None:
		return
		
	service = getService()
	
	startDay, endDay = getPeriod(service, data['year'], data['semester'])
	
	days = getDays(service, startDay, endDay)
	
	addCalendars(service)
	
	calendarId = getCalendarId(service, data['title'], startDay, endDay)
	
	#input("Press Enter to continue...")
	
	createEvents(service, data, days, calendarId)

if __name__ == '__main__':
	if len(sys.argv) != 2:
		print("Usage: $python _programName_ _configFileName_")
	else:
		main(sys.argv.pop(1))