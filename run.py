from dotenv import load_dotenv
import uvicorn

load_dotenv()
if __name__ == '__main__':
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=False)
