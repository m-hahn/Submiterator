#!/usr/bin/env python3

import json, argparse, os, csv
import boto3
import xmltodict
from datetime import datetime
import time

MTURK_SANDBOX_URL = "https://mturk-requester-sandbox.us-east-1.amazonaws.com"
MTURK_ACCESS_KEY = os.environ["MTURK_ACCESS_KEY"]
MTURK_SECRET = os.environ["MTURK_SECRET"]

def main():
    parser = argparse.ArgumentParser(description='Interface with MTurk.')
    parser.add_argument("subcommand", choices=['posthit', 'getresults', 'assignqualification', 'deletehit'],
        type=str, action="store",
        help="choose a specific subcommand.")
    parser.add_argument("nameofexperimentfiles", metavar="label", type=str, nargs="+",
        help="you must have at least one label that corresponds to the " +
        "experiment you want to work with. each experiment has a unique label. " +
        "this will be the beginning of the name of the config file (everything " +
        "before the dot). [label].config.")
    parser.add_argument("-qualification_id", metavar="qualificationid", type=str,
      default = None)

    args = parser.parse_args()

    subcommand = args.subcommand
    labels = args.nameofexperimentfiles

    for label in labels:
        if subcommand == "posthit":
            live_hit, hit_configs = parse_config(label)
            post_hit(label, hit_configs, live_hit)
        elif subcommand == "getresults":
            live_hit, _ = parse_config(label)
            results, results_types = get_results(label, live_hit)
            if len(results["trials"])  > 0:
              write_results(label, results, results_types)
        elif subcommand == "assignqualification":
            live_hit, _ = parse_config(label)
            assign_qualification(label, live_hit, args.qualification_id)
        elif subcommand == "deletehit":
            live_hit, _ = parse_config(label)
            delete_hit(label, live_hit)
            
def mturk_client(live_hit=True):
  if live_hit:
    mturk = boto3.client('mturk',
       aws_access_key_id = MTURK_ACCESS_KEY,
       aws_secret_access_key = MTURK_SECRET,
       region_name='us-east-1'
       )
  else:
    mturk = boto3.client('mturk',
      aws_access_key_id = MTURK_ACCESS_KEY,
      aws_secret_access_key = MTURK_SECRET,
      region_name='us-east-1',
      endpoint_url=MTURK_SANDBOX_URL
    )
  return mturk

def preview_url(hit_id, live_hit=True):
  if live_hit:
    return "https://worker.mturk.com/mturk/preview?groupId=" + hit_id
  else:
    return "https://workersandbox.mturk.com/mturk/preview?groupId=" + hit_id    

def post_hit(experiment_label, hit_configs, live_hit=True):
  hit_id_filename = experiment_label + ".hits"
  
  mturk = mturk_client(live_hit = live_hit)
  with open(hit_id_filename, "a") as hit_id_file:
    print("-" * 80)
    for hit_config in hit_configs:
      new_hit = mturk.create_hit(**hit_config)
      print("Succesfully created hit with {} assignments!".format(new_hit['HIT']["MaxAssignments"]) )
      print("Preview: {}".format(preview_url(new_hit['HIT']['HITGroupId'], live_hit=live_hit)))
      print("-" * 80)
      print(new_hit['HIT']['HITId'], new_hit['HIT']["MaxAssignments"], file=hit_id_file)

def parse_answer(json_str):
  try:
    return json.loads(json_str)
  except json.decoder.JSONDecodeError:
    return json_str

def add_workerid(workerid, answer_name, answer_obj):
  if isinstance(answer_obj, dict):
    answer_obj["workerid"] = workerid
  elif isinstance(answer_obj, list):
    if len(answer_obj) > 0:
      if isinstance(answer_obj[0], dict):
        for x in answer_obj:
          x["workerid"] = workerid
      else:
        new_answer_obj = [{answer_name: x, "workerid": workerid} for x in answer_obj]
        answer_obj = new_answer_obj
  
  return answer_obj


def delete_hit(experiment_label, live_hit=True):
  hit_id_filename = experiment_label + ".hits"
  mturk = mturk_client(live_hit = live_hit)
  print("Retrieving results...")
  print("-" * 80)
  results = {"trials": []}
  result_types = {"trials": "list"}
  with open(hit_id_filename, "r") as hit_id_file:
    for hit_id in hit_id_file:
      hit_id, assignments = hit_id.strip().split()
      mturk.update_expiration_for_hit(HITId=hit_id, ExpireAt=datetime.fromtimestamp(time.time()-1))



def get_results(experiment_label, live_hit=True):
  hit_id_filename = experiment_label + ".hits"
  mturk = mturk_client(live_hit = live_hit)
  print("Retrieving results...")
  print("-" * 80)
  results = {"trials": []}
  result_types = {"trials": "list"}
  with open(hit_id_filename, "r") as hit_id_file:
    for hit_id in hit_id_file:
      hit_id, assignments = hit_id.strip().split()
      worker_results = mturk.list_assignments_for_hit(HITId=hit_id, MaxResults=100)
      print("Completed assignments for HIT \"{}\": {}/{}".format(hit_id, worker_results['NumResults'], assignments))
      print("-" * 80)
      if worker_results['NumResults'] > 0:
        for a in worker_results['Assignments']:
          assignment_id = a["AssignmentId"]
          xml_doc = xmltodict.parse(a['Answer'])
          additional_trial_cols = {}
          worker_id = a["WorkerId"]
          worker_and_assignment_id = worker_id+"_"+assignment_id
          for answer_field in xml_doc['QuestionFormAnswers']['Answer']:
            field_name = answer_field['QuestionIdentifier']
            if field_name == "trials":
              trials = parse_answer(answer_field['FreeText'])
            else:
              answer_obj = parse_answer(answer_field['FreeText'])
              if field_name not in result_types:
                if isinstance(answer_obj, list):
                  result_types[field_name] = "list"
                  results[field_name] = []
                elif isinstance(answer_obj, dict):
                  result_types[field_name] = "dict"
                  results[field_name] = []
                else:
                  result_types[field_name] = "value"
              
              if result_types[field_name] == "list":
                l = add_workerid(worker_and_assignment_id, field_name, answer_obj)
                results[field_name].extend(l)
              elif result_types[field_name] == "dict":
                d = add_workerid(worker_and_assignment_id, field_name, answer_obj)
                results[field_name].append(d)
              elif result_types[field_name] == "value":
                additional_trial_cols["Answer." + field_name] = answer_obj

          trials = add_workerid(worker_and_assignment_id, "trials", trials)
          for t in trials:
             for col in additional_trial_cols:
               t[col] = additional_trial_cols[col]
          results["trials"].extend(trials)
          
  return results, result_types   
 
def anonymize(results, results_types):
  anon_workerids = {}
  c = 0
  for field in results_types:
    if results_types[field] != "value":
      for row in results[field]:
        if row["workerid"] not in anon_workerids:
          anon_workerids[row["workerid"]] = c
          c += 1
        row["workerid"] = anon_workerids[row["workerid"]]
   
  return results, anon_workerids
 
def write_results(label, results, results_types):
  results, anon_workerids = anonymize(results, results_types)
  for field in results_types:
    if results_types[field] != "value" and len(results[field]) > 0:
      out_file_name = label + "-" + field + ".csv"
      with open(out_file_name, "w") as out_file:
        print("Writing results to {} ...".format(out_file_name))
        fieldnames = sorted(list(set().union(*[set(x.keys()) for x in results[field]])))
        writer = csv.DictWriter(out_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results[field])
  
  out_file_name = label + "-workerids.csv"
  with open(out_file_name, "w") as out_file:
    writer = csv.DictWriter(out_file, fieldnames=["workerid", "anon_workerid"])
    writer.writeheader()
    for workerid, anon_workerid in anon_workerids.items():
      writer.writerow({"workerid": workerid, "anon_workerid": anon_workerid})
  print("-" * 80)
      
 
def assign_qualification(label, live_hit, qualificationid):
  f = open(label + '-workerids.csv')
  content = f.read()
  content = content.split('\n')

  workerids = []
  for x in range(1, len(content)-1):
    info = content[x].split(',')
    workerids.append(info[0])

  print("Number of workerids: ",  len(workerids))

  mturk = mturk_client(live_hit)

  for workerid in workerids:
    response = mturk.associate_qualification_with_worker(
      QualificationTypeId=qualificationid,
      WorkerId=workerid,
      IntegerValue=100,
      SendNotification=True
    )
    print(response)

def parse_config(experiment_label, output_dir=""):
  config_filename = experiment_label + ".config"

  # load config file
  with open(config_filename, "r") as config_file:
    config = json.load(config_file)

  is_live_hit = config["liveHIT"] == "yes"

  hit_options = dict()
  # prepare question XML
  hit_options["Question"] = """
    <ExternalQuestion xmlns='http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd'>
      <ExternalURL>{}</ExternalURL>
      <FrameHeight>{}</FrameHeight>
    </ExternalQuestion>
    """.format(config["experimentURL"] ,  config["frameheight"])

  # set other properties
  hit_options["Title"] = config["title"]
  hit_options["Description"] = config["description"]
  hit_options["Keywords"] = config["description"]
  hit_options["Reward"] = config["reward"]
  hit_options["LifetimeInSeconds"] = int(config["hitlifetime"])
  hit_options["AssignmentDurationInSeconds"] = int(config["assignmentduration"])
  hit_options["AutoApprovalDelayInSeconds"] = int(config["autoapprovaldelay"])
  hit_options["QualificationRequirements"] = []
  
  
  if config["USonly?"].lower() in ["y", "true", "yes", "t", "1"]:
    hit_options["QualificationRequirements"].append({
      "QualificationTypeId": "00000000000000000071",
      "Comparator": "EqualTo",
      "LocaleValues": [
        {"Country": "US"}
      ],
      "ActionsGuarded": "DiscoverPreviewAndAccept"
    })
    
  if config["minPercentPreviousHITsApproved"] != "none":
    hit_options["QualificationRequirements"].append({
      "QualificationTypeId": "000000000000000000L0",
      "Comparator": "GreaterThanOrEqualTo",
      "IntegerValues": [
        int(config["minPercentPreviousHITsApproved"])
      ],
      "ActionsGuarded": "DiscoverPreviewAndAccept"
    })
  
  if "minNumPreviousHITsApproved" in config and config["minNumPreviousHITsApproved"] != "none":
    hit_options["QualificationRequirements"].append({
      "QualificationTypeId": "00000000000000000040",
      "Comparator": "GreaterThanOrEqualTo",
      "IntegerValues": [
        int(config["minNumPreviousHITsApproved"])
      ],
      "ActionsGuarded": "DiscoverPreviewAndAccept"
    })
  
  if "doesNotHaveQualification" in config and config["doesNotHaveQualification"] != "none":
    hit_options["QualificationRequirements"].append({
      "QualificationTypeId": config["doesNotHaveQualification"],
      "Comparator": "DoesNotExist",
      "ActionsGuarded": "DiscoverPreviewAndAccept"
    })
  
  if "doesHaveQualification" in config and config["doesHaveQualification"] != "none":
    qualification_ids = (config["doesHaveQualification"] 
                         if "," not in config["doesHaveQualification"] 
                         else config["doesHaveQualification"].split(","))
    hit_options["QualificationRequirements"].append({
      "QualificationTypeId": qualification_ids,
      "Comparator": "Exists",
      "ActionsGuarded": "DiscoverPreviewAndAccept"
    })

  max_assignments =  int(config["numberofassignments"])
  if "assignmentsperhit" in config:
    assignments_per_hit = int(config["assignmentsperhit"])
  else:
    assignments_per_hit = max_assignments
  
  hit_assignments = [assignments_per_hit] * int(max_assignments / assignments_per_hit)
  if max_assignments % assignments_per_hit > 0:
    hit_assignments.append(max_assignments % assignments_per_hit)
  
  
  hit_options_list = []
  
  # create an options dictionary for each batch
  for assignments in hit_assignments:
    options = dict(hit_options)
    options["MaxAssignments"] = assignments
    hit_options_list.append(options)
    
  return is_live_hit, hit_options_list
  
if __name__ == '__main__':
  main()
