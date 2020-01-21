import datetime
import pickle
import os.path
import json
from flask import Flask, request, jsonify, render_template
from flask_restful import Resource, Api
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

def calc_week_dates():
    today = datetime.date.today()
    weekday = today.isoweekday()
    return {
        1: (today + datetime.timedelta(days=(1 - weekday) % 7)),
        2: (today + datetime.timedelta(days=(2 - weekday) % 7)),
        3: (today + datetime.timedelta(days=(3 - weekday) % 7)),
        4: (today + datetime.timedelta(days=(4 - weekday) % 7)),
        5: (today + datetime.timedelta(days=(5 - weekday) % 7)),
        6: (today + datetime.timedelta(days=(6 - weekday) % 7)),
        7: (today + datetime.timedelta(days=(7 - weekday) % 7)),
    }


availability = {
    1 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
    2 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
    3 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
    4 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
    5 : [],
    6 : [],
    7 : [(datetime.time(hour=21), datetime.timedelta(hours=3))],
}

appointment_slot_size = datetime.timedelta(minutes=20)

policy = {
    "max_appointments_per_person" : 1
}

iso_weekdays = {
    1:"Monday",
    2:"Tuesday",
    3:"Wednesday",
    4:"Thursday",
    5:"Friday",
    6:"Saturday",
    7:"Sunday",
}

def calc_appointment_slots(availability, appointment_slot_size):
    slots = {}
    dates = calc_week_dates()

    for weekday in availability:
        slots[weekday] = []
        for availability_start, availability_duration in availability[weekday]:
            availability_start = datetime.datetime.combine(dates[weekday], availability_start)
            appointment_start = availability_start
            while (
                    appointment_start+appointment_slot_size <=
                    availability_start+availability_duration and
                    appointment_start > datetime.datetime.now()):
                slots[weekday].append({
                    "start" : appointment_start,
                    "len": appointment_slot_size,
                    "booked":False,
                })
                appointment_start += appointment_slot_size

    return slots


class Calendar():
    # If modifying these scopes, delete the file token.pickle.
    #SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    SCOPES = ['https://www.googleapis.com/auth/calendar']

    def __init__(self):
        self.service = None
        self.calendar_id = None

    def connect(self, calendar_name):
        creds = None
        # Check for existing auth token
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        self.service = build('calendar', 'v3', credentials=creds)


        calendars_result = self.service.calendarList().list().execute()
        for calendar in calendars_result['items']:
            if calendar['summary'] == calendar_name:
                self.calendar_id = calendar['id']

        if(self.calendar_id is None):
            print("Cannot find calendar: " + calendar_name)
            return -1

    def get_schedule(self):
        now = datetime.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
        next_week = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat()+'Z'
        appointments = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            timeMax=next_week,
            singleEvents=True,
            orderBy='startTime').execute().get('items', [])

        slots = calc_appointment_slots(availability, appointment_slot_size)
        for event in appointments:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            appt_start = (datetime.datetime.fromisoformat(start)).replace(tzinfo=None)
            appt_end = (datetime.datetime.fromisoformat(end)).replace(tzinfo=None)

            for slot in slots[appt_start.isoweekday()]:
                if ((appt_start < slot["start"]+slot["len"] and
                     slot["start"]+slot["len"] <= appt_end) or
                    (appt_start <= slot["start"] and
                     slot["start"] < appt_end) or
                    (slot["start"] <= appt_start and
                     appt_end <= slot["start"]+slot["len"])):
                    slot["booked"] = True

        ret = {}
        for weekday in slots:
            ret[weekday] = {
                "name": iso_weekdays[weekday],
                "date": "",
                "appts": [],
            }
            for slot in slots[weekday]:
                ret[weekday]["appts"].append((
                    slot["start"].strftime("%-I:%M %p"),
                    slot["booked"]))
                ret[weekday]["date"] = slot["start"].strftime("%-m/%d")
        return ret


    def has_appointment(self, email, netid):
        # 'Z' indicates UTC time
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        next_week = (datetime.datetime.utcnow() +
            datetime.timedelta(days=7)).isoformat() + 'Z'
        appointments = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            timeMax=next_week,
            singleEvents=True,
            orderBy='startTime').execute().get('items', [])

    def book_appointment(self, start_time, netid, email, name):

        pass


app = Flask(__name__)
api = Api(app)
calendar = Calendar()

class Schedule(Resource):
    def post(self):
        return calendar.get_schedule()

class Appointment(Resource):
    def post(self):
        if ('start' in request.json and
            'netid' in request.json and
            'email' in request.json and
            'name' in request.json):

            return calendar.book_appointment(
                request.json['start'],
                request.json['netid'],
                request.json['email'],
                request.json['name'])


@app.route("/")
def index():
    schedule = calendar.get_schedule()
    today = datetime.date.today()

    ss = []
    ss.append(schedule[(today + datetime.timedelta(days=0)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=1)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=2)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=3)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=4)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=5)).isoweekday()])
    ss.append(schedule[(today + datetime.timedelta(days=6)).isoweekday()])

    return render_template("index.html",
        today=datetime.date.today().strftime("%a"),
        schedule1=ss[:3],
        schedule2=ss[3:])

api.add_resource(Schedule, '/schedule')
api.add_resource(Appointment, '/appointment')


def main():
    calendar.connect('CPSC 323 Office Hours Appointments')
    app.run()



if __name__ == '__main__':
    main()
