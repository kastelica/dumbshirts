from app import app  # exposes `app` for Gunicorn

if __name__ == "__main__":
	app.run()
