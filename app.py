from os import environ, makedirs, name, path, rename, uname
from selectors import EVENT_READ, DefaultSelector
from subprocess import Popen, PIPE
from shutil import rmtree
from urllib.request import Request, urlopen
from webbrowser import open as webopen
from sys import stderr

#from asyncio import run
#from hypercorn.config import Config as cornConfig
#from hypercorn.asyncio import serve
#from asgiref.wsgi import WsgiToAsgi


from flask import (Flask, g, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_babel import Babel, gettext
from flask_sqlalchemy import SQLAlchemy
from PIL.Image import open as imgopen
from plyer import notification
from werkzeug.exceptions import RequestEntityTooLarge

if name == 'nt':
    data_dir = path.join(environ['APPDATA'], 'Weblauncher')
elif uname().sysname == 'Linux':
    if environ.get('XDG_DATA_HOME') is not None:
        data_dir = path.expandvars('$XDG_DATA_HOME/Weblauncher')
    else:
        data_dir = path.expandvars('$HOME/.local/share/Weblauncher')
else:
    data_dir = path.expanduser('~/.Weblauncher')
if not path.exists(data_dir):
    makedirs(data_dir)

config_names = ['config_wideprefix', 'config_wideworkdir']

app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = path.join(
    'sqlite:///' + data_dir, 'configs.db')
app.config['UPLOAD_FOLDER'] = resources_dir = path.join(data_dir, 'resources')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
app.config['LANGUAGES'] = {
    'en': 'English',
    'zh': '中文'
}


def get_locale():
    if 'lang' in request.cookies:
        return request.cookies.get("lang")
    else:
        return request.accept_languages.best_match(app.config['LANGUAGES'])


def get_timezone():
    user = getattr(g, 'user', None)
    if user is not None:
        return user.timezone


def configlocalizedname(config):
    if config.name == config_names[0]:
        return gettext("Global prefix")
    if config.name == config_names[1]:
        return gettext("Default working directory")
    return '!ErrorNoName!'

    # 烂到要死的解决方法
    # return eval(''.join(['config.', get_locale(), '_name']))


db = SQLAlchemy(app)
babel = Babel(app, locale_selector=get_locale, timezone_selector=get_timezone)


class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(100), nullable=False)


class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(), unique=False, nullable=False)
    workdir = db.Column(db.String(), unique=False)
    prefix = db.Column(db.String(), unique=False)
    command = db.Column(db.String(), unique=False, nullable=False)


@app.route('/favicon.ico')
def favicon_ico():
    return send_from_directory(path.join(app.root_path, 'static'),
                               'pic/favicon.ico')


@app.route('/dummy-sw.js')
def sw():
    return send_from_directory(path.join(app.root_path, 'static'),
                               'js/dummy-sw.js')


@app.route('/app.webmanifest')
def manifest():
    return send_from_directory(path.join(app.root_path, 'static'),
                               'app.webmanifest')


@app.route('/')
def index():
    # 渲染 index.html 模板文件，并将 programs, configs 变量传递给模板
    return render_template('index.html', languages=app.config['LANGUAGES'], get_locale=get_locale, configlocalizedname=configlocalizedname, programs=Program.query.all(), configs=Config.query.all())


@app.route('/upload/<path:program_id>', methods=['GET', 'POST'])
def upload(program_id):
    try:
        filedest = path.join(resources_dir, program_id.split('-')[-1])
        if request.content_type == 'application/json':
            url = request.get_json().get('url')
            urlfile = urlopen(Request(url, headers={'User-Agent': 'Mozilla'}))
            if int(urlfile.headers['Content-Length']) > app.config['MAX_CONTENT_LENGTH']:
                raise RequestEntityTooLarge()
            basename = save_file(urlfile, filedest)
        else:
            file = request.files['file']
            basename = save_file(file, filedest)
        return basename, 201
    except ValueError as e:
        return str(e), 202
    except RequestEntityTooLarge:
        return gettext("File size exceeds the limit"), 413
    except Exception as e:
        return str(e), 400


def save_file(imgfile, filedest):
    with imgopen(imgfile) as img:
        img.verify
        match img.format:
            case 'ICO':
                filedest = path.join(filedest, 'icon.ico')
                img = img.resize([256, 256], resample=4)
                img = img.convert('RGBA')
                img.save(filedest, format='ICO', sizes=[(256, 256)])
            case 'JPEG' | 'PNG':
                filedest = path.join(filedest, 'library.jpg')
                if img.format == 'JPEG':
                    img.save(filedest, format='JPEG', quality='keep')
                else:
                    img = img.convert('RGB')
                    img.save(filedest, format='JPEG')
    return path.basename(filedest)


@app.route('/data/<path:filename>', methods=['GET'])
def data(filename):
    try:
        return send_from_directory(data_dir, filename)
    except:
        return '', 204


@app.route('/picview')
def picview():
    return render_template('picview.html', programs=Program.query.all(), str=str, fallback_thumbnail=url_for('static', filename='pic/fallback.png'))


@app.route('/tableview')
def tableview():
    return render_template('tableview.html', str=str, programs=Program.query.all())


@app.route('/detail/<int:program_id>', methods=['GET'])
def detail(program_id):
    return render_template('detail.html', get_locale=get_locale, program=Program.query.get_or_404(program_id))


@app.route('/detail_folder/<int:program_id>', methods=['GET'])
def detail_folder(program_id):
    program_dir = path.join(resources_dir, str(program_id))
    webopen('file:///' + program_dir)
    return ('', 204)


@app.route('/config', methods=['POST'])
def config():
    for key, value in request.form.items():
        config = Config.query.filter_by(name=key).first()
        if config:
            # 如果已经存在该记录，更新 value 字段
            config.value = value
        else:
            # 如果不存在该记录，插入一条新记录
            config = Config(name=key, value=value)
            db.session.add(config)
    db.session.commit()
    return ('', 204)
    # return redirect(url_for('index'))


@app.route('/add/<int:program_realid>', methods=['GET', 'POST'])
def add_program(program_realid):
    id = request.form['program_id']
    name = request.form['program_name']
    workdir = request.form['program_workdir']
    prefix = request.form['program_prefix']
    command = request.form['program_command']
    if id == '0':
        new_program = Program(name=name, workdir=workdir,
                              prefix=prefix, command=command)
        db.session.add(new_program)
        db.session.commit()
        new_program_dir = path.join(resources_dir, str(new_program.id))
        new_program_dirbak = path.join(new_program_dir + '.bak')
        try:
            makedirs(new_program_dir)
        except FileExistsError:
            try:
                rename(new_program_dir, new_program_dirbak)
            except FileExistsError:
                rmtree(path.join(new_program_dir + '.bak'))
                rename(new_program_dir, new_program_dirbak)
            makedirs(new_program_dir)
    else:
        program = Program.query.get_or_404(program_realid)
        program_dir = path.join(resources_dir, str(program_realid))
        program_destdir = path.join(resources_dir, str(id))
        # 在更改id的时候移动资源文件夹
        if str(program_realid) == id:
            pass
        elif Program.query.get(id):
            return render_template('detail.html', alert='1', formerid=id, program=program)
        elif path.exists(program_destdir):
            return render_template('detail.html', alert='2', formerid=id, program=program)
        else:
            try:
                rename(program_dir, program_destdir)
            except FileNotFoundError:
                makedirs(program_destdir)
            except:
                return 'failed move data', 400
        program.id = id
        program.name = name
        program.workdir = workdir
        program.prefix = prefix
        program.command = command
        db.session.commit()
        return redirect(url_for('detail', program_id=id, need_reload='1'))
    return redirect(request.referrer)


@app.route('/delete/<int:program_id>', methods=['GET'])
def delete_program(program_id):
    respath = path.join(resources_dir, str(program_id))
    resbakpath = path.join(respath + '.bak')
    try:
        rename(respath, resbakpath)
    except FileExistsError:
        rmtree(resbakpath)
        rename(respath, resbakpath)
    except FileNotFoundError:
        pass
    except:
        return 'delete failed', 400
    program = Program.query.get_or_404(program_id)
    db.session.delete(program)
    db.session.commit()
    return redirect(request.referrer)
    # return redirect(url_for('index'))


@app.route('/launch/<int:program_id>', methods=['GET'])
def launch(program_id):
    # 环境变量
    program = Program.query.get_or_404(program_id)
    pdatadir = path.join(resources_dir, str(program.id))
    wideprefix = Config.query.filter_by(name='config_wideprefix').first()
    wideworkdir = Config.query.filter_by(name='config_wideworkdir').first()

    # 发送通知，顺便防止开多
    iconpath = path.join(pdatadir, 'icon.ico')
    if not path.exists(iconpath):
        iconpath = path.join(app.root_path, 'static/pic/logo.png')
    try:
        sendnote(iconpath, program.name,
                 'ID: ' + str(program.id) + '\n' + gettext("Just been launched"), 5)
    except:
        return 'too often', 204

    # 命令环境变量
    command = " ".join(
        [wideprefix.value, program.prefix, program.command])
    workdir = path.expandvars(
        program.workdir
    ) or path.expandvars(
        wideworkdir.value
    ) or path.expanduser('~')
    #programenv = 

    # 启动进程
    with Popen(command, cwd=workdir, shell=True,
               universal_newlines=True, stdout=PIPE, stderr=PIPE) as process:
        the_stdout, the_stderr, the_retcode = printlog(process, program.name)
        with open(path.join(pdatadir, 'stderr.log'), 'w') as err:
            err.write(the_stderr)
        with open(path.join(pdatadir, 'stdout.log'), 'w') as out:
            out.write(the_stdout)

        # todo: 这里改一下，如果失败则在模板里显示提示
        if the_retcode == 0:
            return 'success', 204
        else:
            sendnote(iconpath, program.name,
                     'Crashed' + '\n' 'exitcode: ' + str(the_retcode), 10)
            return 'failed', 204
    return 'not right', 400


def printlog(p, who):
    # 获取程序LOG
    # https://stackoverflow.com/a/61585093
    # Read both stdout and stderr simultaneously
    sel = DefaultSelector()
    sel.register(p.stdout, EVENT_READ)
    sel.register(p.stderr, EVENT_READ)
    the_stderr = ''
    the_stdout = ''
    ok = True
    while ok:
        for key, val1 in sel.select():
            line = key.fileobj.readline()
            if not line:
                ok = False
                break
            if key.fileobj is p.stdout:
                the_stdout += line
                print(f"[{who}] STDOUT: {line}", end="")
            else:
                the_stderr += line
                the_stdout += line
                print(f"[{who}] STDERR: {line}", end="", file=stderr)
    return the_stdout, the_stderr, p.wait()


def sendnote(iconpath, title, message, timeout):
    notification.notify(
        app_name='Weblauncher',
        app_icon=iconpath,
        title=title,
        message=message,
        timeout=timeout
    )


if __name__ == '__main__':
    db.create_all()
    # 向 Config 表中插入默认配置项
    for name in config_names:
        if Config.query.filter_by(name=name).first() is None:
            config = Config(name=name, value='')
            db.session.add(config)
    db.session.commit()
    for program in Program.query.all():
        program_dir = path.join(data_dir, 'resources', str(program.id))
        if not path.exists(program_dir):
            makedirs(program_dir)
    app.run(host='::', port=2023, debug=True)
