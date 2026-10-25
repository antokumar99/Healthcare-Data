.PHONY: up install all test clean
up:        ; docker compose up -d
install:   ; pip install -r requirements.txt
all:       ; python run_pipeline.py all
test:      ; pytest -q
clean:     ; rm -rf data/raw/*.csv data/staging/*.csv reports/*
