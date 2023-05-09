# pytrainbrick

[bricknil](https://github.com/virantha/bricknil) inspired python program to control duplo train 10874!

## Setup and launch

Unix:
```sh
python -m pip install --user virtualenv
python -m venv env
source env/bin/activate
pip install -r requirements.txt
python ./pytrainbrick/main.py
```

Windows:
```bat
python -m pip install --user virtualenv
python -m venv env
env\Scripts\activate.bat
pip install -r requirements.txt
python pytrainbrick\main.py
```

Now power on the lego duplo train on a circular track. Its led color should change to red. It will perform some accelerations and stops. Some sounds will be played. Unlike using official app to control the train, the train motor will not stop if it encounters resistance.