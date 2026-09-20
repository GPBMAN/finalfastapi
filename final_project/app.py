
from fastapi import FastAPI, HTTPException, Depends, Request, Cookie, File, Form,status, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from project_models import User, Base, async_session, engine, Problem, AdminResponse, ServiceRecord
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from datetime import datetime, timedelta
import bcrypt


SECRET_KEY = 'kW!8729ew95P$be5j532#8Qlv;3&5tJ3'
ALGORITHM = "HS256"

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

#Set up functions

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.on_event("startup")
async def on_startup():
    await init_db()


@app.exception_handler(Exception)
async def internal_server_error_handler(request: Request, exc: Exception):
    return templates.TemplateResponse(request=request, name="500.html", context={"exception": exc}, status_code=500)


def get_current_user(access_token: str = Cookie(None)):
    if not access_token:
        raise HTTPException(status_code=401, detail="Неавторизовано")
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        role = payload.get("role")
        if user_id is None or role is None:
            raise HTTPException(status_code=401)
        return user_id, role
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Недійсний токен")


def admin_required(user_data: tuple = Depends(get_current_user)) -> bool:
    user_id, role = user_data
    if role != "admin":
        raise HTTPException(status_code=403, detail="Доступ лише для адміністраторів")
    return True

#Routes 

@app.get("/test_error")
async def test_error():
    math = 2 + "2"



@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request,name="home.html")



@app.get("/register", response_class=HTMLResponse)
async def get_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")



@app.post("/register")
async def post_register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_session)
):

    query = select(User).where((User.username == username) | (User.email == email))
    result = await db.execute(query)
    existing_user = result.scalars().first()

    if existing_user:
        return templates.TemplateResponse(
            request=request, 
            name="register.html", 
            context={"error": "Username or email already exists"}
        )


    new_user = User(username=username, email=email)
    new_user.set_password(password)
    
    db.add(new_user)
    await db.commit()

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)



@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")



@app.post("/login")
async def post_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_session)
):
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    user = result.scalars().first()


    if not user or not user.verify_password(password):
        return templates.TemplateResponse(
            request=request, 
            name="login.html", 
            context={"error": "Invalid username or password"},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    token_data = {
        "user_id": user.id,
        "role": "admin" if user.is_admin else "user",
        "exp": datetime.utcnow() + timedelta(hours=24*3)
    }

    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)


    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60*60*24*3,
        samesite="lax"
    )
    
    return response



@app.get("/add_problem", response_class=HTMLResponse)
async def get_problem(request: Request):
    return templates.TemplateResponse(request=request, name="problem.html")



@app.post("/add_problem")
async def post_problem(
    request: Request,
    title: str = Form(..., max_length=100),
    description: str = Form(..., max_length=500),
    image: UploadFile = Form(...),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    
    if not image.content_type.startswith("image/"):
        return {"error": "file is not an image"}

    img_path = None
    if image.filename:
            file_location = f"user_problem_image/{image.filename}"
            with open('static/'+ file_location, "wb+") as f:
                f.write(await image.read())
            img_path = file_location


    new_problem = Problem(
        title=title,
        description=description,
        user_id=current_user[0],
        image_url=img_path
    )

    db.add(new_problem)
    await db.commit()
    await db.refresh(new_problem)



@app.get('/new_problems')
async def user_problems(request: Request, session: AsyncSession = Depends(get_session) , is_admin: int = Depends(admin_required)):
    new_problems = await session.execute(select(Problem.id, Problem.title, Problem.description, Problem.date_created).filter_by(status="В обробці"))
    new_problems = new_problems.all()
    print(new_problems)

    return templates.TemplateResponse(
        request=request, 
        name="all_problems.html", 
        context={"problems": new_problems}
    )



@app.get('/problem')
async def user_problem(problem_id: int, request: Request, session: AsyncSession = Depends(get_session), is_admin: int = Depends(admin_required)):
    problem = await session.execute(select(Problem).filter_by(id = problem_id))
    problem = problem.scalars().first()
    return templates.TemplateResponse(
        request=request, 
        name="problem_check.html", 
        context={"problem": problem}
    )



@app.post('/problem')
async def take_problem(request: Request, current_user: User = Depends(get_current_user),id:int=Form(), session: AsyncSession = Depends(get_session), is_admin: int = Depends(admin_required)):
    problem = await session.execute(select(Problem).filter_by(id=id))
    problem = problem.scalar_one_or_none()
    if problem:
        problem.status = 'У роботі'
        problem.admin_id = current_user[0]
        session.add(problem)
        await session.commit()
        await session.refresh(problem)

    return templates.TemplateResponse(
        request=request, 
        name="problem_check.html", 
        context={"problem": problem, "message":'Заявку взято в роботу!'}
    )



@app.get('/admin_problems')
async def admin_problams(request: Request, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),is_admin: int = Depends(admin_required)):
    new_problems = await session.execute(select(Problem).filter_by(admin_id = current_user[0]))
    new_problems = new_problems.scalars().all()
    return templates.TemplateResponse(name='admin_problems.html',request=request, context={'problems': new_problems})



@app.get('/add_answer')
async def add_answer( problem_id: int,request: Request, is_admin: int = Depends(admin_required)):
    return templates.TemplateResponse(name='add_answer.html', request=request, context={'id':problem_id})



@app.post('/add_answer')
async def add_answer(request: Request,problem_id:int = Form() , current_user: User = Depends(get_current_user), message:str= Form(),session: AsyncSession = Depends(get_session), is_admin: int = Depends(admin_required) ):
    new_answer = AdminResponse(message=message, admin_id = current_user[0], problem_id= problem_id)
    session.add(new_answer)
    await session.commit()

    problem = await session.execute(select(Problem).filter_by(id=problem_id))
    problem = problem.scalars().one_or_none()
    problem.status = 'Є відповідь'
    session.add(problem)
    await session.commit()
    return templates.TemplateResponse(name='add_answer.html', request=request, context={'message':'Відповідь збережена!'})



@app.get('/my_all_problems')
async def my_all_prblms(request: Request, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    all_problems = await session.execute(select(Problem).filter_by(user_id=current_user[0]))
    problems = all_problems.scalars().all()
    return templates.TemplateResponse(name='all_my_problems.html',request=request,context={'problems':problems})



@app.get('/check_message')
async def check_message(id :int, request: Request, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    problem = await session.execute(select(Problem).filter_by(id=id))
    problem = problem.scalars().one_or_none()
    problem_answer = await session.execute(select(AdminResponse).filter_by(problem_id=id))
    problem_answer = problem_answer.scalars().one_or_none()
    return templates.TemplateResponse(name='check_message.html',request=request, context={'problem':problem, 'answer':problem_answer})



@app.get('/service_complete')
async def service_complete_get(problem_id:int, request: Request):
    return templates.TemplateResponse(name='service_complete.html',request=request, context={"problem_id":problem_id})



@app.post('/service_complete')
async def service_complete(request: Request, work_done: str = Form(), parts_used: str = Form(), problem_id:int = Form(),current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session), is_admin: int = Depends(admin_required)):
    problem = await session.execute(select(Problem).filter_by(id=problem_id))
    problem = problem.scalars().one_or_none()
    warranty_info = f"# {problem_id}\\nТип послуги: сервісне обслуговування\\nДата початку робіт: {problem.date_created.date()}\\nДата завершення робіт: {date.today()}\\nГарантія розповсюджується на деталі що використовувалися в роботі, та механізми що були полагоджені\\nДата завершення гарантії: {date.today() + timedelta(days=180)}"
    new_service_record = ServiceRecord(work_done=work_done, parts_used=parts_used, problem_id=problem_id,warranty_info=warranty_info)
    session.add(new_service_record)
    await session.commit()
    problem.status = 'Завершено'
    session.add(problem)
    await session.commit()
    return templates.TemplateResponse(name='service_complete.html', request=request, context={"message": 'Запис додано!'})



@app.get('/service_record_review')
async def service_record_review(id:int, request: Request, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    problem = await session.execute(select(Problem).filter_by(id=id))
    problem = problem.scalars().one_or_none()
    service_record = await session.execute(select(ServiceRecord).filter_by(problem_id = id))
    my_service_record = service_record.scalars().one_or_none()
    return templates.TemplateResponse(name='service_check.html',request=request, context={'problem':problem, 'service_record':my_service_record})



@app.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Ви вийшли з системи"}