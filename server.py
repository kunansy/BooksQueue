#!/usr/bin/env python3
import datetime
import logging
from typing import Any

import ujson
from pydantic import BaseModel, ValidationError, validator, constr, conint
from sanic import Sanic, Request, response, HTTPResponse
from sanic_jinja2 import SanicJinja2
from sanic_session import Session

from src import db_api
from src import logger as logger_
from src import tracker as trc


logging.getLogger('sanic.error').disabled = True


app = Sanic(__name__, log_config=logger_.LOGGING_CONFIG)
app.static('/static', './static')

session = Session(app)
jinja = SanicJinja2(app, session=session)

log = trc.Log(full_info=True)
tracker = trc.Tracker(log)
logger = logging.getLogger('ReadingTracker')


class Material(BaseModel):
    class Config:
        extra = 'forbid'

    title: constr(strip_whitespace=True, min_length=1)
    authors: constr(strip_whitespace=True, min_length=1)
    pages: conint(gt=0)
    tags: constr(strip_whitespace=True)


class Note(BaseModel):
    class Config:
        extra = 'forbid'

    material_id: conint(gt=0)
    content: constr(strip_whitespace=True, min_length=1)
    chapter: conint(gt=0)
    page: conint(gt=0)

    def __repr__(self) -> str:
        fields = ', '.join(
            f"{key}='{val}'"
            for key, val in self.dict().items()
        )
        return f"{self.__class__.__name__}({fields})"


class LogRecord(BaseModel):
    class Config:
        extra = 'forbid'

    material_id: conint(gt=0)
    date: datetime.date
    count: conint(gt=0)

    @validator('date')
    def validate_date(cls,
                      date: datetime.date) -> datetime.date:
        if date > trc.today():
            raise ValueError("You cannot set log to the future")
        return date

    @validator('material_id')
    def validate_material_id(cls,
                             material_id: int) -> int:
        if not tracker.does_material_exist(material_id):
            raise ValueError(f"Material {material_id=} doesn't exist")
        return material_id

    def __repr__(self) -> str:
        data = ', '.join(
            f"{key}={value}"
            for key, value in self.dict()
        )
        return f"{self.__class__.__name__}({data})"


@app.get('/favicon.ico')
async def favicon(request: Request) -> HTTPResponse:
    return response.json({})


@app.get('/materials/queue')
@jinja.template('queue.html')
async def get_queue(request: Request) -> dict[str, Any]:
    return {
        'materials': tracker.queue
    }


@app.get('/materials/add')
@jinja.template('add_material.html')
async def add_material(request: Request) -> dict[str, Any]:
    """ Add a material to the queue """
    return {
        'title': request.ctx.session.get('title', ''),
        'authors': request.ctx.session.get('authors', ''),
        'pages': request.ctx.session.get('pages', ''),
        'tags': request.ctx.session.get('tags', ''),
    }


@app.post('/materials/add')
async def add_material(request: Request) -> HTTPResponse:
    """ Add a material to the queue """
    key_val = {
        key: val[0]
        for key, val in request.form.items()
    }
    try:
        material = Material(**key_val)
    except ValidationError as e:
        context = ujson.dumps(e.errors(), indent=4)
        logger.warning(f"Validation error:\n{context}")

        jinja.flash(
            request,
            f'Validation error: {e.raw_errors[0].exc}',
            'error'
        )
        request.ctx.session.update(
            **key_val
        )
        return response.redirect('/materials/add')
    else:
        request.ctx.session.clear()

    try:
        tracker.add_material(**material.dict())
    except Exception as e:
        jinja.flash(request, str(e), 'error')

        request.ctx.session.update(
            **material.dict()
        )
    else:
        request.ctx.session.clear()
        jinja.flash(request, "Material added", 'success')
    finally:
        return response.redirect('/materials/add')


@app.post('/materials/start/<material_id:int>')
async def start_material(request: Request,
                         material_id: int) -> HTTPResponse:
    try:
        tracker.start_material(material_id)
    except trc.BaseDBError as e:
        jinja.flash(request, str(e), 'error')
    else:
        jinja.flash(request, f"Material {material_id=} started", 'success')
    finally:
        return response.redirect('/material/queue')


@app.post('/materials/complete/<material_id:int>')
async def complete_material(request: Request,
                            material_id: int) -> HTTPResponse:
    try:
        tracker.complete_material(material_id)
    except trc.BaseDBError as e:
        jinja.flash(request, str(e), 'error')
    else:
        jinja.flash(request, f"Material {material_id=} completed", 'success')
    finally:
        return response.redirect('/materials/reading')


@app.get('/materials/reading')
@jinja.template('reading.html')
async def get_reading_materials(request: Request) -> dict[str, Any]:
    stat = [
        tracker.get_material_statistic(
            ms.material.material_id, material=ms.material, status=ms.status
        )
        for ms in tracker.reading
    ]
    return {
        'statistics': stat,
        'DATE_FORMAT': trc.DATE_FORMAT
    }


@app.get('/materials/completed')
@jinja.template('completed.html')
async def get_completed_materials(request: Request) -> dict:
    stat = [
        tracker.get_material_statistic(
            ms.material.material_id, material=ms.material, status=ms.status
        )
        for ms in tracker.processed
    ]
    return {
        'statistics': stat,
        'DATE_FORMAT': trc.DATE_FORMAT
    }


@app.get('/reading_log')
@jinja.template('reading_log.html')
async def get_reading_log(request: Request) -> dict[str, Any]:
    return {
        'log': log.log,
        'DATE_FORMAT': trc.DATE_FORMAT,
        'EXPECTED_COUNT': trc.PAGES_PER_DAY
    }


@app.get('/reading_log/add')
@jinja.template('add_log_record.html')
async def add_reading_log(request: Request) -> dict[str, Any]:
    return {
        'material_id': log.reading_material,
        'date': trc.today()
    }


@app.post('/reading_log/add')
async def add_log_record(request: Request) -> HTTPResponse:
    key_val = {
        key: val[0]
        for key, val in request.form.items()
    }

    try:
        record = LogRecord(**key_val)
    except ValidationError as e:
        context = ujson.dumps(e.errors(), indent=4)
        logger.warning(f"Validation error:\n{context}")

        jinja.flash(
            request,
            f'Validation error: {e.raw_errors[0].exc}',
            'error'
        )
        return response.redirect('/reading_log/add')

    try:
        tracker.log._set_log(**record.dict())
    except Exception as e:
        jinja.flash(request, str(e), 'error')
    else:
        log.dump()
        jinja.flash(request, 'Record added', 'success')
    finally:
        return response.redirect('/reading_log/add')


@app.get('/notes')
@jinja.template('notes.html')
async def get_notes(request: Request):
    material_id = request.args.get('material_id')
    try:
        notes = tracker.get_notes(material_id)
    except ValueError:
        jinja.flash(request, 'Enter an integer', 'error')
        return response.redirect('/notes')

    if not notes:
        jinja.flash(request, f'No notes {material_id=} found', 'error')
    else:
        jinja.flash(request, f"{len(notes)} notes found", 'success')

    titles = {
        note.material_id: db_api.get_title(note.material_id)
        for note in notes
    }
    return {
        'notes': notes,
        'titles': titles,
        'DATE_FORMAT': trc.DATE_FORMAT
    }


@app.get('/notes/add')
@jinja.template('add_note.html')
async def add_note(request: Request) -> dict[str, Any]:
    return {
        'material_id': request.ctx.session.get('material_id', ''),
        'content': request.ctx.session.get('content', ''),
        'page': request.ctx.session.get('page', ''),
        'chapter': request.ctx.session.get('chapter', ''),
    }


@app.post('/notes/add')
async def add_note(request: Request) -> HTTPResponse:
    key_val = {
        key: val[0]
        for key, val in request.form.items()
    }

    try:
        note = Note(**key_val)
    except ValidationError as e:
        context = ujson.dumps(e.errors(), indent=4)
        logger.warning(f"Validation error:\n{context}")

        jinja.flash(request, 'Validation error', 'error')
        return response.redirect('/notes/add')

    try:
        tracker.add_note(**note.dict())
    except trc.MaterialNotFound as e:
        jinja.flash(request, str(e), 'error')
    except ValueError as e:
        jinja.flash(request, str(e), 'error')
    else:
        jinja.flash(request, 'Note added', 'success')
        request.ctx.session.update(
            **note.dict(exclude={'content'})
        )
    finally:
        return response.redirect('/notes/add')


@app.get('/')
@jinja.template('index.html')
async def home(request: Request) -> None:
    pass


@app.exception(ValidationError)
def validation_error_handler(request: Request,
                             exception: ValidationError) -> HTTPResponse:
    context = ujson.dumps(exception.errors(), indent=4)
    logger.error(f"Validation error was not handled:\n{context}")

    return response.json(exception.errors(), status=400, indent=4)


@app.exception(Exception)
def error_handler(request: Request,
                  exception: Exception) -> HTTPResponse:
    try:
        ex_json = exception.json()
    except:
        ex_json = ''
    try:
        req_json = request.json
    except:
        req_json = ''

    context = {
        'ok': False,
        "wrong_request": req_json,
        "error": {
            "type": exception.__class__.__name__,
            "text": str(exception),
            "args": exception.args,
            "json": ex_json
        }
    }

    logger.error(ujson.dumps(context, indent=4))
    return response.json(context, status=500, indent=4)


if __name__ == "__main__":
    app.run(
        port=8080,
        debug=True,
    )
