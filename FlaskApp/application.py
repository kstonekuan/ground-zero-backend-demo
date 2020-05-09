# Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except
# in compliance with the License. A copy of the License is located at
#
# https://aws.amazon.com/apache-2-0/
#
# or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"Demo Flask application"
import sys

import requests
import boto3
from flask import Flask, render_template_string
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from docx import Document

import config
import util

import json

application = Flask(__name__)
application.secret_key = config.FLASK_SECRET

### FlaskForm set up
class UploadForm(FlaskForm):
    file = FileField(validators=[
        FileRequired()
    ])

def getTemplates(s3_client):
    response = s3_client.list_objects(
        Bucket=config.TEMPLATES_BUCKET,
        Prefix="paragraphs/"
    )

    labels_response = s3_client.list_objects(
        Bucket=config.TEMPLATES_BUCKET,
        Prefix="labels/"
    )
    
    senti_response = s3_client.list_objects(
        Bucket=config.TEMPLATES_BUCKET,
        Prefix="sentiment/"
    )
    templates = []
    i = 0
    if 'Contents' in response and response['Contents']:
        for obj in response['Contents']:
            templates.append({})
            txt = s3_client.get_object(Bucket=config.TEMPLATES_BUCKET, Key=obj['Key'])
            body = txt['Body'].read().decode("utf-8")
            templates[i] = {"text": body}
            i += 1
        i = 0
        for obj in labels_response['Contents']:
            result = s3_client.get_object(Bucket=config.TEMPLATES_BUCKET, Key=obj['Key'])
            body = json.loads(result['Body'].read().decode("utf-8"))
            templates[i]["labels"] = []
            if body["KeyPhrases"]:
                for phrase in body["KeyPhrases"]:
                    if phrase["Score"] >= 0.99999 : 
                        templates[i]["labels"].append(phrase["Text"])
            i += 1
        
        i = 0
        for obj in senti_response['Contents']:
            result = s3_client.get_object(Bucket=config.TEMPLATES_BUCKET, Key=obj['Key'])
            body = json.loads(result['Body'].read().decode("utf-8"))
            templates[i]["sentiments"] = body["SentimentScore"]
            i += 1
            
    return templates

@application.route("/", methods=('GET', 'POST'))
def home():
    """Homepage route"""

    #####
    # s3 getting a list of templates in the bucket
    #####
    s3_client = boto3.client('s3', aws_access_key_id=config.AWS_ID, aws_secret_access_key=config.AWS_SECRET, region_name='us-west-2')
    
    templates = getTemplates(s3_client)
            

    comprehend = boto3.client('comprehend', aws_access_key_id=config.AWS_ID, aws_secret_access_key=config.AWS_SECRET, region_name='us-west-2')
    form = UploadForm()
    document = None
    if form.validate_on_submit():
        document = Document(form.file.data)
        if document:
            for para in document.paragraphs:
                #######
                # s3 excercise - save the file to a bucket
                #######
                name = util.random_hex_bytes(8)
                
                if len(para.text) > 15:
                    s3_client.put_object(
                        Bucket=config.TEMPLATES_BUCKET,
                        Key="paragraphs/" + name + '.txt',
                        Body=para.text,
                        ContentType='text/plain'#'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    )
                
                    text = para.text
                    
                    result = json.dumps(comprehend.detect_key_phrases(Text=text, LanguageCode='en'), sort_keys=True, indent=4)
                    
                    s3_client.put_object(
                        Bucket=config.TEMPLATES_BUCKET,
                        Key="labels/" + name + ".json",
                        Body=result,
                        ContentType='application/json'
                    )
                    
                    sentiment = json.dumps(comprehend.detect_sentiment(Text=text, LanguageCode='en'), sort_keys=True, indent=4)
                    
                    s3_client.put_object(
                        Bucket=config.TEMPLATES_BUCKET,
                        Key="sentiment/" + name + ".sentiment.json",
                        Body=sentiment,
                        ContentType='application/json'
                    )
            templates = getTemplates(s3_client)

    return render_template_string("""
            {% extends "main.html" %}
            {% block content %}
            <h4>Upload Document</h4>
            <form method="POST" enctype="multipart/form-data" action="{{ url_for('home') }}">
                {{ form.csrf_token }}
                  <div class="control-group"
                    <label class="control-label">Document</label>
                    {{ form.file() }}
                  </div>

                    &nbsp;
                   <div class="control-group">
                    <div class="controls">
                        <input class="btn btn-primary" type="submit" value="Upload">
                    </div>
                  </div>
            </form>

            <hr/>
            {% if document %}
            <h3>Uploaded!</h3>
            {% endif %}
            
            {% if templates %}
            <hr/>
            <h4>Templates</h4><hr/>
            {% for template in templates %}
                <span class="label label-default">Neutral: {{"%.2f" % template['sentiments']['Neutral']}}</span>
                <span class="label label-success">Positive: {{"%.2f" % template['sentiments']['Positive']}}</span>
                <span class="label label-warning">Mixed: {{"%.2f" % template['sentiments']['Mixed']}}</span>
                <span class="label label-danger">Negative: {{"%.2f" % template['sentiments']['Negative']}}</span>
                <br/>
                {% for label in template['labels'] %}
                    <span class="label label-info">{{label}}</span>
                {% endfor %}
                <br/>
                <span>{{template['text']}}</span><br/><hr/>
            {% endfor %}
            {% endif %}

            {% endblock %}
                """, form=form, document=document, templates=templates)


@application.route("/info")
def info():
    "Webserver info route"
    metadata = "http://169.254.169.254"
    instance_id = requests.get(metadata +
                               "/latest/meta-data/instance-id").text
    availability_zone = requests.get(metadata +
                                     "/latest/meta-data/placement/availability-zone").text

    return render_template_string("""
            {% extends "main.html" %}
            {% block content %}
            <b>instance_id</b>: {{instance_id}} <br/>
            <b>availability_zone</b>: {{availability_zone}} <br/>
            <b>sys.version</b>: {{sys_version}} <br/>
            {% endblock %}""",
                                  instance_id=instance_id,
                                  availability_zone=availability_zone,
                                  sys_version=sys.version)


if __name__ == "__main__":
    # http://flask.pocoo.org/docs/0.12/errorhandling/#working-with-debuggers
    # https://docs.aws.amazon.com/cloud9/latest/user-guide/app-preview.html
    use_c9_debugger = False
    application.run(use_debugger=not use_c9_debugger, debug=True,
                    use_reloader=not use_c9_debugger, host='0.0.0.0', port=int(config.PORT_NUM))
