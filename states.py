from aiogram.fsm.state import State, StatesGroup

class Interview(StatesGroup):
    start = State()
    level = State()
    interview = State()
