__all__ = ('get_materials', 'get_status', 'get_completed_materials',
           'get_free_materials', 'complete_material')

import datetime
from contextlib import contextmanager
from os import environ
from typing import ContextManager

from sqlalchemy import Column, ForeignKey, Integer, String, Date, create_engine, \
    MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session


DATE_FORMAT = '%d-%m-%Y'

Base = declarative_base()


class Material(Base):
    __tablename__ = 'material'

    material_id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    authors = Column(String, nullable=False)
    size = Column(String, nullable=False,
                  doc="Amount of pages, count of lectures etc.")
    tags = Column(String)

    def __repr__(self) -> str:
        return "Material(" \
               f"{self.material_id}, {self.title}, " \
               f"{self.authors}, {self.size}, {self.tags})"


class Status(Base):
    __tablename__ = 'status'

    status_id = Column(Integer, primary_key=True)
    material_id = Column(Integer,
                         ForeignKey('material.material_id'),
                         nullable=False,
                         unique=True)
    begin = Column(Date)
    end = Column(Date)

    def __repr__(self) -> str:
        if begin := self.begin:
            begin = begin.strftime(DATE_FORMAT)
        if end := self.end:
            end = end.strftime(DATE_FORMAT)

        return "Status(" \
               f"{self.status_id}, {self.material_id}, " \
               f"{begin}, {end})"


metadata = MetaData()

engine = create_engine(environ['DB_URI'], echo=True, encoding='utf-8')
Base.metadata.create_all(engine)

conn = engine.connect()


@contextmanager
def session(**kwargs) -> ContextManager[Session]:
    new_session = Session(**kwargs, bind=engine, expire_on_commit=False)
    try:
        yield new_session
        new_session.commit()
    except:
        new_session.rollback()
        raise
    finally:
        new_session.close()


def today() -> datetime.date:
    return datetime.datetime.now().date()


def get_materials(materials_ids: list[int]) -> list[Material]:
    with session() as ses:
        if materials_ids:
            return ses.query(Material).filter(
                Material.material_id.in_(materials_ids)).all()
        return ses.query(Material).all()


def get_free_materials() -> list[Material]:
    with session() as ses:
        return ses.query(Material).join(Status).filter(Status.end == None)


def get_completed_materials() -> list[Material]:
    with session() as ses:
        return ses.query(Material).join(Status).filter(Status.end != None)


def get_status(*,
               status_id: int = None) -> list[Status]:
    with session() as ses:
        if status_id is None:
            return ses.query(Status).all()
        return ses.query(Status).filter(Status.status_id == status_id).all()


def add_materials(materials: list[dict]) -> None:
    with session() as ses:
        for material in materials:
            material = Material(**material)
            ses.add(material)


def start_material(*,
                   material_id: int,
                   start_date: datetime.date = None) -> None:
    with session() as ses:
        start_date = start_date or today()

        if start_date > today():
            raise ValueError("Start date mus be less than today,"
                             "but %s found", start_date)

        started_material = Status(
            material_id=material_id, begin=start_date)
        ses.add(started_material)


def complete_material(*,
                      material_id: int) -> None:
    pass
