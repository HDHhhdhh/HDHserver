from sqlalchemy import (create_engine, Column as C, String, Integer, Enum,
                        Date, ForeignKey, Boolean, Text)
from sqlalchemy.orm import declarative_base, relationship
from config import DB_URL

Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)

class Student(Base):
    __tablename__ = "students"
    id    = C(String, primary_key=True)  # uuid4
    name  = C(String, nullable=False)
    curriculum = C(String)               # 미적분1 …
    day1 = C(String); day2 = C(String); day3 = C(String)

class Video(Base):
    __tablename__ = "videos"
    id = C(Integer, primary_key=True, autoincrement=True)
    curriculum = C(String); chapter = C(Integer); title = C(String); url = C(Text)

class Progress(Base):
    __tablename__ = "progress"
    student_id = C(String, ForeignKey("students.id"), primary_key=True)
    date   = C(Date, primary_key=True)
    video_id = C(Integer, ForeignKey("videos.id"), primary_key=True)
    status   = C(Enum("완료","일부","미완료", name="status_e"), default="미완료")

class Material(Base):
    __tablename__ = "materials"
    id = C(Integer, primary_key=True, autoincrement=True)
    curriculum = C(String); filename = C(String); title = C(String)

Base.metadata.create_all(engine)
