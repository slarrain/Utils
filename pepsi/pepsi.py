from bottle import route, run, request, response, template
import subprocess

@route('/')
def hello():
    return  '''
            <html>
                <form method="post" action="/plusone">
                    <input type="submit" value="+1"/>
                </form>
                <form method="post" action="/minusone">
                    <input type="submit" value="-1"/>
                </form>
                <h2><a href="/plusone"> +1 </a> <br>
                <a href="/minusone"> -1 </a> </h2> <br>

                <br><br>
                <a href="/check"> Check</a>
            </html>
            '''

@route('/plusone', method='POST')
def plus():
    if modify(1):
        return "200"

@route('/minusone', method='POST')
def minus():
    if modify(-1):
        n = int(check())
        if n<=1:
            command = "echo -e 'ALERTA!\n Solo queda {0} Pepsi.\n POR FAVOR IR A COMPRAR A LA BREVEDAD!\n Gracias.' | mail -s 'Pepsis' santiagolarrain@gmail.com".format(n)
            print command
            p = subprocess.Popen([command])
            print p.poll()
        return "200"

def modify(n):
    with open ('db', 'r+') as db:
        orig = int(db.read())
        new_n = orig+n
        db.seek(0)
        db.write(str(new_n))
        db.truncate()
    return True

@route('/check')
def check():
    with open ('db', 'r') as db:
        orig = db.read()
        return orig


run(host='0.0.0.0', port=9999, debug=True, reloader=True)

# echo "ALERTA! Solo queda 1 Pepsi. POR FAVOR IR A COMPRAR A LA BREVEDAD! Gracias." | mail -s "Pepsis" santiagolarrain@gmail.com

# echo -e 'ALERTA!\n Solo queda 1 Pepsi.\n POR FAVOR IR A COMPRAR A LA BREVEDAD!\n Gracias.' | mail -s "Pepsis" santiagolarrain@gmail.com
