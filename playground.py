from phi.playground import Playground, serve_playground_app
from main import agent  # Import the agent from your main module

# Set up the playground with the imported agent
app = Playground(agents=[agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("playground:app", reload=True)
