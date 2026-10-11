"""Persistent community records, one-use recognition tickets and anonymous moderation.

No photos, API keys, raw IPs or client identifiers are returned in facility records.
SQLite transactions make report deduplication and hiding atomic across workers.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
try:
    from .services import ServiceError
    from .local_facilities import distance, segment_distance
except ImportError:
    from services import ServiceError
    from local_facilities import distance, segment_distance

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tickets (token TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
 payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS facilities (id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
 latitude REAL NOT NULL, longitude REAL NOT NULL, location_source TEXT NOT NULL,
 confidence REAL NOT NULL, created_at REAL NOT NULL, hidden INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reports (facility_id TEXT NOT NULL REFERENCES facilities(id),
 reporter TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(facility_id, reporter));
CREATE TABLE IF NOT EXISTS limits (actor TEXT NOT NULL, action TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS limits_time ON limits(created_at);
'''

@contextmanager
def database():
    path = Path(os.getenv('COMMUNITY_DB_PATH', str(Path(__file__).with_name('data') / 'community.sqlite3')))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=10)
    except (OSError, sqlite3.Error):
        raise ServiceError('Community storage is temporarily unavailable.', 503) from None
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise ServiceError('Community storage is temporarily unavailable.', 503) from None
    finally:
        db.close()


def threshold():
    try: return max(3, min(20, int(os.getenv('COMMUNITY_REPORT_THRESHOLD', '3'))))
    except ValueError: return 3


def secret(db):
    db.execute("INSERT OR IGNORE INTO settings VALUES ('identity_secret', ?)", (secrets.token_hex(32),))
    return db.execute("SELECT value FROM settings WHERE key='identity_secret'").fetchone()[0].encode()


def identity(cookie, network):
    with database() as db:
        key = secret(db)
    value, _, signature = (cookie or '').partition('.')
    if len(value) != 32 or not hmac.compare_digest(signature, hmac.new(key, value.encode(), hashlib.sha256).hexdigest()):
        value = secrets.token_hex(16)
    signed = value + '.' + hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
    # Network hash is used only for bounded abuse controls, not as proof of identity.
    network_hash = hmac.new(key, network.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(value.encode()).hexdigest(), signed, network_hash


def rate_limit(actor, action, maximum, seconds=3600):
    now = time.time()
    with database() as db:
        db.execute('DELETE FROM limits WHERE created_at < ?', (now-86400,))
        count = db.execute('SELECT COUNT(*) FROM limits WHERE actor=? AND action=? AND created_at>?',
                           (actor, action, now-seconds)).fetchone()[0]
        if count >= maximum:
            raise ServiceError('Too many community requests. Please try again later.', 429)
        db.execute('INSERT INTO limits VALUES (?,?,?)', (actor, action, now))


def ticket(owner, kind, payload):
    token = secrets.token_urlsafe(32)
    with database() as db:
        db.execute('DELETE FROM tickets WHERE expires < ?', (time.time(),))
        db.execute('INSERT INTO tickets VALUES (?,?,?,?,?)',
                   (token, owner, kind, json.dumps(payload), time.time()+900))
    return token


def read_ticket(db, token, owner, kind):
    row = db.execute('SELECT payload FROM tickets WHERE token=? AND owner=? AND kind=? AND expires>?',
                     (token, owner, kind, time.time())).fetchone()
    if not row:
        raise ServiceError('Photo or address confirmation expired or was already used. Please try again.', 422)
    return json.loads(row['payload'])


def facility(row):
    return {'id': row['id'], 'name': row['name'], 'type': row['type'],
            'latitude': row['latitude'], 'longitude': row['longitude'],
            'coordinate_source': 'community_' + row['location_source'], 'access_verified': False,
            'metadata': {}, 'source': {'kind': 'community', 'name': 'Community submission',
                'created_at': row['created_at'], 'ai_confidence': row['confidence']},
            'report_count': row['report_count'], 'report_threshold': threshold()}


def active():
    with database() as db:
        rows = db.execute('SELECT f.*, (SELECT COUNT(*) FROM reports r WHERE r.facility_id=f.id) AS report_count '
                          'FROM facilities f WHERE hidden=0').fetchall()
    return [facility(row) for row in rows]


def nearby(latitude, longitude, radius, category=None):
    return [f for f in active() if (category is None or f['type']==category)
            and distance(latitude, longitude, f['latitude'], f['longitude']) <= radius]


def corridor(coordinates, radius, category=None):
    if not coordinates: return []
    return [f for f in active() if (category is None or f['type']==category) and
            min([distance(f['latitude'],f['longitude'],lat,lon) for lon,lat in coordinates] +
                [segment_distance(f['latitude'],f['longitude'],a,b) for a,b in zip(coordinates,coordinates[1:])]) <= radius]


def create(owner, submission):
    with database() as db:
        recognition = read_ticket(db, submission.recognition_token, owner, 'photo')
        if recognition['facility_type']=='unknown' or recognition['confidence'] < .75:
            raise ServiceError('The photo does not clearly show a supported facility. Try another photo.', 422)
        if submission.location_source=='address':
            location = read_ticket(db, submission.address_token or '', owner, 'address')
            if location['coordinates'] != [submission.longitude, submission.latitude]:
                raise ServiceError('Choose a confirmed address search result.', 422)
        for existing in db.execute('SELECT * FROM facilities WHERE hidden=0 AND type=?', (recognition['facility_type'],)):
            if distance(submission.latitude,submission.longitude,existing['latitude'],existing['longitude']) < 15:
                raise ServiceError('A community facility of this type already exists within 15 meters.', 409)
        identifier = 'community/' + str(uuid.uuid4())
        name = submission.name.strip()
        if not name: raise ServiceError('Enter a facility name.', 422)
        db.execute('INSERT INTO facilities(id,name,type,latitude,longitude,location_source,confidence,created_at) VALUES (?,?,?,?,?,?,?,?)',
                   (identifier,name,recognition['facility_type'],submission.latitude,submission.longitude,
                    submission.location_source,recognition['confidence'],time.time()))
        db.execute('DELETE FROM tickets WHERE token=?', (submission.recognition_token,))
        if submission.address_token: db.execute('DELETE FROM tickets WHERE token=?', (submission.address_token,))
        row=db.execute('SELECT *, 0 AS report_count FROM facilities WHERE id=?',(identifier,)).fetchone()
        return facility(row)


def report(identifier, owner, reason):
    with database() as db:
        row=db.execute('SELECT hidden FROM facilities WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ServiceError('Community facility not found.',404)
        if row['hidden']: raise ServiceError('This facility has already been removed from discovery.',410)
        if db.execute('SELECT 1 FROM reports WHERE facility_id=? AND reporter=?',(identifier,owner)).fetchone():
            raise ServiceError('You have already reported this facility.',409)
        db.execute('INSERT INTO reports VALUES (?,?,?,?)',(identifier,owner,reason,time.time()))
        count=db.execute('SELECT COUNT(*) FROM reports WHERE facility_id=?',(identifier,)).fetchone()[0]
        hidden=count>=threshold()
        if hidden: db.execute('UPDATE facilities SET hidden=1 WHERE id=?',(identifier,))
        return {'report_count':count,'report_threshold':threshold(),'removed':hidden}
