from fastapi import FastAPI

app = FastAPI(title="OptiFuel")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
