# ExitZero Test Folder

Run each file to generate errors, then diagnose with ExitZero.

## Python errors
    python src/buggy.py 2>&1 | tee error.log
    python -m exitzero --file error.log

## Network error
    python src/network_bug.py 2>&1 | tee error.log
    python -m exitzero --file error.log

## Type error
    python src/type_bug.py 2>&1 | tee error.log
    python -m exitzero --file error.log
