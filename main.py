import datetime
import pickle
import os.path
import json
from flask import Flask, request, jsonify, render_template
from flask_restful import Resource, Api
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


class Constants():
    iso_weekdays = {
        1:"Monday",
        2:"Tuesday",
        3:"Wednesday",
        4:"Thursday",
        5:"Friday",
        6:"Saturday",
        7:"Sunday",
    }


class Policy():
    def __init__(self):
        self.max_appointments_per_person = 1
        self.allowed_email_domains = ["yale.edu", "bulldogs.yale.edu"]

    def is_email_allowed(self, email):
        return (self.allowed_email_domains is None or
            email[email.find("@")+1:] in self.allowed_email_domains)

class Schedule():
    def __init__(self):
        self.appointment_slot_size = datetime.timedelta(minutes=20)
        self.timezone = datetime.timezone(-datetime.timedelta(hours=5))
        self.availability = {
            1 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
            2 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
            3 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
            4 : [(datetime.time(hour=18), datetime.timedelta(hours=6))],
            5 : [],
            6 : [],
            7 : [(datetime.time(hour=21), datetime.timedelta(hours=3))],
        }

    def calc_week_dates(self):
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


    def calc_appointment_slots(self):
        slots = {}
        dates = self.calc_week_dates()

        for weekday in self.availability:
            slots[weekday] = []
            for availability_start, availability_duration in self.availability[weekday]:

                availability_start = datetime.datetime.combine(
                    dates[weekday],
                    availability_start)
                appointment_start = availability_start

                while(  appointment_start+self.appointment_slot_size <=
                        availability_start+availability_duration):
                    slots[weekday].append({
                        "start" : appointment_start,
                        "len": self.appointment_slot_size,
                        "booked":False,
                    })
                    appointment_start += self.appointment_slot_size
        return slots





class Calendar():
    # If modifying these scopes, delete the file token.pickle.
    SCOPES = ['https://www.googleapis.com/auth/calendar']

    def __init__(self, policy, schedule):
        self.service = None
        self.calendar_id = None
        self.policy = policy
        self.schedule = schedule

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

    def iso_str_to_naive_dt(self, s):
        return datetime.datetime.fromisoformat(s).replace(tzinfo=None)

    def utc_dt_to_iso_str(self, dt):
        return dt.isoformat()+'Z'

    def naive_dt_to_iso_str(self, dt):
        return dt.replace(tzinfo=self.schedule.timezone).isoformat()

    def rotate_schedule_today_index(self, schedule):
        today = datetime.date.today()
        return (
            schedule[(today + datetime.timedelta(days=0)).isoweekday()],
            schedule[(today + datetime.timedelta(days=1)).isoweekday()],
            schedule[(today + datetime.timedelta(days=2)).isoweekday()],
            schedule[(today + datetime.timedelta(days=3)).isoweekday()],
            schedule[(today + datetime.timedelta(days=4)).isoweekday()],
            schedule[(today + datetime.timedelta(days=5)).isoweekday()],
            schedule[(today + datetime.timedelta(days=6)).isoweekday()]
        )

    def format_schedule(self, schedule):
        ret = {}
        for weekday in schedule:
            ret[weekday] = {
                "name": Constants.iso_weekdays[weekday],
                "date": "",
                "appts": [],
            }
            for slot in schedule[weekday]:
                ret[weekday]["appts"].append((
                    slot["start"].strftime("%-I:%M %p"),
                    slot["booked"]))
                ret[weekday]["date"] = slot["start"].strftime("%-m/%d/%y")
        return self.rotate_schedule_today_index(ret)

    def build_schedule(self):
        # 'Z' indicates UTC time
        now_utc_dt = datetime.datetime.utcnow()
        now_dt = datetime.datetime.now()
        next_week_utc_dt = now_utc_dt + datetime.timedelta(days=7)

        # Lookup existing appointments in gcal
        appointments = self.service.events().list(
            calendarId = self.calendar_id,
            timeMin = self.utc_dt_to_iso_str(now_utc_dt),
            timeMax = self.utc_dt_to_iso_str(next_week_utc_dt),
            singleEvents = True,
            orderBy = 'startTime').execute().get('items', [])

        #Compute all possible appointment slots for the week
        slots = self.schedule.calc_appointment_slots()

        # Mark slots as booked
        for event in appointments:
            a_start = self.iso_str_to_naive_dt(event['start']['dateTime'])
            a_end   = self.iso_str_to_naive_dt(event['end']['dateTime'])

            for slot in slots[a_start.isoweekday()]:
                s_start = slot["start"]
                s_end   = slot["start"] + slot["len"]

                slot["booked"] = (
                    (a_start < s_end and s_end <= a_end) or
                    (a_start <= s_start and s_start < a_end) or
                    (s_start <= a_start and a_end <= s_end) or
                    (s_start <= now_dt))

        return slots


    def lookup_appointment_request(self, start_time):
        schedule = self.build_schedule()
        start_time_dt = datetime.datetime.strptime(
            start_time, "%m/%d/%y %I:%M %p")

        for slot in schedule[start_time_dt.isoweekday()]:
            if slot["start"] == start_time_dt:
                return slot

        return None



    def num_appointments(self, email):
        user = email[:email.find("@")]
        #TODO
        return 0

    def book_appointment(self, start_time, email, name):
        user = email[:email.find("@")]

        if(start_time is None or email is None or name is None):
            return (False, "Error")

        if(not self.policy.is_email_allowed(email)):
            return (False, "Email not allowed")

        if( self.num_appointments(email) >=
            self.policy.max_appointments_per_person):
            return (False, "Too many appointments")

        slot = self.lookup_appointment_request(start_time)
        if(slot is None or slot["booked"]):
            return (False, "That time in not available")


        result = self.service.events().insert(
            calendarId = self.calendar_id,
            conferenceDataVersion = 1,
            sendUpdates = "all",
            body={
                "summary" : "323 Appointment with " + name,
                "description" : "Please come prepared with information about how you have been debugging, what the problem is, what you have tried to do so far, etc.",
                "start" : {
                    "dateTime":self.naive_dt_to_iso_str(slot["start"]),
                    "timeZone": "America/New_York",
                },
                "end" : {
                    "dateTime":self.naive_dt_to_iso_str(
                        slot["start"]+slot["len"]),
                    "timeZone": "America/New_York",
                },
                "organizer" : {
                    "self" : True,
                },
                "attendees" : [{
                    "displayName":name,
                    "email":email,
                }],
            }).execute()

        return (True, "Appointment booked: " + result.get("htmlLink"))





def main():
    app = Flask(__name__)
    api = Api(app)

    gcal = Calendar(Policy(), Schedule())

    @app.route("/", methods=['GET','POST'])
    def index():
        if (request.method == 'POST'):
            success, message = gcal.book_appointment(
                request.form.get('appt'),
                request.form.get('email'),
                request.form.get('name'))
            print(message)

        schedule = gcal.format_schedule(gcal.build_schedule())

        return render_template("index.html",
            today=datetime.date.today().strftime("%a"),
            schedule1=schedule[:3],
            schedule2=schedule[3:])

    gcal.connect('CPSC 323 Office Hours Appointments')
    app.run()



if __name__ == '__main__':
    main()
