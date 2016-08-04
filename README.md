# Blackboard SCORM analysis

![Part of a report](http://numbas.github.io/blackboard-scorm-analysis/blackboard-report.png)

Blackboard doesn't make it easy to analyse data to do with SCORM packages: the built-in SCORM reports don't give much useful information and are tedious to generate, and it's unclear where in the database the SCORM data lies.

We discovered that the _Export/Archive Course_ tool collects together all of the attempt data for SCORM packages in a way that can be easily interpreted.

This tool allows you to analyse all of the information held by Blackboard about SCORM packages in your course, by presenting the data from a course archive nicely. It's designed to work with SCORM packages generated using [Numbas](http://www.numbas.org.uk); other packages might work, but we don't guarantee it.

## First, a warning

We've found that Blackboard often loses data, or saves inconsistent data. That can mean that a student's attempt is missing, or the question scores don't tally up with the part scores, or the suspend data and correct answers don't match what the student saw.

This happens in a small but significant number of cases. It should be obvious on looking at an individual attempt whether there's something wrong, but bear in mind that inconsistencies can appear if you try to do analyse the set of attempts as a whole.

We've also had a report that if any student has unenrolled from a course, the export will stop as soon as it tries to match an attempt by that student with their Grade Centre entry. This means that tests will appear to have far fewer attempts in the analysis tool than are shown in the Grade Centre.

Finally, the reported durations of attempts only rarely match up with reality. Best not to try to draw any conclusions from those.

## Installation

The tool is a self-contained Python Flask server, which you can run on your own PC. Install [Python 3](https://www.python.org/downloads/), and then install the required Python packages by running the following command:

    pip install flask lxml pygal

Obtain a copy of the Blackboard SCORM analysis server (either clone this repository or [download a .zip](https://github.com/numbas/blackboard-scorm-analysis/archive/master.zip)) and extract it into a directory on your PC.
    
To start the server, run

    python server.py

And open `http://localhost:5000` in your browser.

## Uploading a course

* Go to your Blackboard course, and click on _Packages and Utilities_, then _Export/Archive Course_.
* Click on the _Archive Course_ button.
* In the following form, make sure _Include Grade Centre History_ is ticked, then click _Submit_.
* It takes a while to create the archive. You'll get an email when it's ready - once that happens, go back to the _Export/Archive Course_ page and click on the .zip file to download it.
* In the Blackboard SCORM analysis tool, click on _Upload a zip file_, and then upload the file you just got from Blackboard.

You can update a course's data by generating another archive and uploading that. The old version will be automatically rewritten.

