#!/bin/python3
from app import db, config_names, Config, Program, path, makedirs, app, resources_dir
from asyncio import run
from hypercorn.config import Config as hypercornConfig
from hypercorn.asyncio import serve
from asgiref.wsgi import WsgiToAsgi

hypercornconfig = hypercornConfig()
hypercornconfig.bind = ["[::]:2023", "0.0.0.0:5000"]

if __name__ == '__main__':
    db.create_all()
    for name in config_names:
        if Config.query.filter_by(name=name).first() is None:
            config = Config(name=name, value='')
            db.session.add(config)
    db.session.commit()
    for program in Program.query.all():
        program_dir = path.join(resources_dir, str(program.id))
        if not path.exists(program_dir):
            makedirs(program_dir)
    run(serve(WsgiToAsgi(app), hypercornconfig))
