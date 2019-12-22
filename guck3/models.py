from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, BooleanField, SubmitField, TextField, HiddenField
from wtforms import validators, FileField, FloatField, PasswordField
from wtforms.validators import DataRequired


class UserLoginForm(FlaskForm):
    email = TextField('Username/Email', [validators.Required(), validators.Length(min=4, max=25)])
    password = PasswordField('Password', [validators.Required(), validators.Length(min=6, max=200)])
    submit_u = SubmitField(label="Log In")
