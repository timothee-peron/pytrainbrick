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

Now power on the lego duplo train on a **circular track**. In order to connect, the train LED must be blinking.

The included demo has the following features:
  - color change
  - acceleration, stops, reverse
  - sounds
Unlike using official app to control the train, the train motor will not stop if it encounters resistance.
