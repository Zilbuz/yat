#!/usr/bin/env python
#-*- coding:utf-8 -*-

u"""
Yat Library

Minimalistic library to manipulate the data of yat: the configuration file and
the sqlite database.

This file also contain the exceptions used by yat programs.


           DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE 
                   Version 2, December 2004 

 Copyright (C) 2010 
    Basile Desloges <basile.desloges@gmail.com>
    Simon Chopin <chopin.simon@gmail.com>

 Everyone is permitted to copy and distribute verbatim or modified 
 copies of this license document, and changing it is allowed as long 
 as the name is changed. 

            DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE 
   TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION 

  0. You just DO WHAT THE FUCK YOU WANT TO. 

This program is free software. It comes without any warranty, to
the extent permitted by applicable law. You can redistribute it
and/or modify it under the terms of the Do What The Fuck You Want
To Public License, Version 2, as published by Sam Hocevar. See
http://sam.zoy.org/wtfpl/COPYING for more details.
"""

import datetime
import locale
import os
import pickle
import re
import sqlite3
import sys
import time

class YatLib:

    def __init__(self):
        u"""Constructor:
            * load the configuration file
            * open a connection with the database
            * initialise some variables
        """
        # Default encoding
        self.enc = locale.getpreferredencoding()

        # Default input : stdin
        self.input = sys.stdin

        # Default output : stdout
        self.output = sys.stdout

        # Loading configuration
        self.config = {}
        try:
            with open(os.environ.get("HOME") + "/.yatrc", "r") as config_file:
                for line in config_file:
                    if not (re.match(r'^\s*#.*$', line) or re.match(r'^\s*$', line)):
                        line = re.sub(r'\s*=\s*', "=", line, 1)
                        line = re.sub(r'\n$', r'', line)
                        opt = line.split('=', 1)
                        self.config[opt[0]] = opt[1]
            config_file.close()
        except IOError:
            # No .yatrc
            pass

        # For each option, loading default if it isn't defined
        self.config["yatdir"] = self.config.get("yatdir", "~/.yat")
        self.config["default_list"] = self.config.get("default_list", "nolist")
        self.config["default_tag"] = self.config.get("default_tag", "notag")
        self.config["default_priority"] = self.config.get("default_priority", "1")

        # Default timestamp: infinite
        self.config["default_date"] = float('+inf')

        # Create yat directory
        if self.config["yatdir"][0] == "~":
            self.config["yatdir"] = os.environ.get("HOME") + self.config["yatdir"][1:]
        if not os.path.isdir(self.config["yatdir"]):
            os.makedirs(self.config["yatdir"], mode=0700)

        # Connect to sqlite db
        self.__sql = sqlite3.connect(self.config["yatdir"] + "/yat.db")

        # Use Row as row_factory to add access by column name and other things
        self.__sql.row_factory = sqlite3.Row

        # Add a function to support the REGEXP() operator
        def regexp(expr, item):
            # Replace all * and ? with .* and .? (but not \* and \?)
            regex = re.sub(r'([^\\]?)\*', r'\1.*', expr)
            regex = re.sub(r'([^\\])\?', r'\1.?', regex)
            # Replace other \ with \\
            regex = re.sub(r'\\([^*?])', r'\\\\\1', regex)
            # Replace ^ and $ by \^ and \$
            regex = re.sub(r'\^', r'\^', regex)
            regex = re.sub(r'\$', r'\$', regex)
            # Add ^ and $ to the regexp
            regex = r'^' + regex + r'$'
            return len(re.findall(regex, item)) > 0
        self.__sql.create_function("regexp", 2, regexp)
    
        # Verify the existence of the database and create it if it doesn't exist
        # (very basic)
        try:
            with self.__sql:
                self.__sql.execute("select * from tags")
        except sqlite3.OperationalError:
            # Create tables
            with self.__sql:
                self.__sql.execute("""
                    create table tasks (
                        id integer primary key,
                        task text,
                        priority int,
                        due_date real,
                        tags text,
                        list text,
                        completed integer,
                        last_modified real,
                        created real
                    )""")
                self.__sql.execute("""
                    create table tags (
                        id integer primary key,
                        name text,
                        priority integer,
                        last_modified real,
                        created real
                        )""")
                self.__sql.execute("""
                    create table lists (
                        id integer primary key,
                        name text,
                        priority integer,
                        last_modified real,
                        created real
                        )""")
                self.__sql.execute("""insert into tags values (null, "notag", -1,
                        ?, ?)""", (self.get_time(), self.get_time()))
                self.__sql.execute("""insert into lists values (null, "nolist",
                        -1, ?, ?)""", (time.time(), self.get_time()))
                self.__sql.commit()

        # Get application pid
        self.__pid = os.getpid()

        # Hidden config (regexp)
        self.config["re.id"] = u"\d*?"
        self.config["re.priority"] = u"\d"
        self.config["re.date"] = u"(?P<x1>\d\d)/(?P<x2>\d\d)/(?P<year>\d{4})(:(?P<hour>\d?\d)(:(?P<minute>\d\d))?(?P<apm>am|pm)?)?"
        self.config["re.tag_name"] = u".*"
        self.config["re.tags_list"] = u"{0}?(,{0}?)*".format(
                self.config["re.tag_name"])
        self.config["re.list_name"] = u".*"
        pass

    def get_tasks(self, ids=None, regexp=None, group=True, order=True, group_by="list",
            order_by=["reverse:priority", "due_date"]):
        u"""Method to get the tasks from the database, group them by list or
        tag, and order them according to the parameters. This function return an
        array of tasks if group is False, and an array of tuple (group,
        list_of_tasks) if group is True, where group is a list or a tag, and
        list_of_tasks, well... a list of tasks...

        The grouping is done only if "group" is set to True
        
        The ordering is done only if "order" and "group" are set to True. 
        
        If no ids and no regexp are provided, assume regexp="*"

        The group_by arg can only contain "list" or "tag"

        The order_by contains an array with column names. The tasks will be
        ordered by the first element, then the second... To reverse the sorting
        order, use something like "reverse:column_name" (see default parameters
        for an example)

        params:
            - ids (array<int>)
            - regexp (string)
            - group (boolean)
            - order (boolean)
            - group-by ("list" or "tag")
            - order-by (array<string>)
        """

        tasks = []
        # Extract tasks from the database
        if ids != None:
            with self.__sql:
                for i in ids:
                    tasks.extend(self.__sql.execute(
                        u"select * from tasks where id=?", (i,)).fetchall())
        if regexp != None:
            with self.__sql:
                tasks.extend(self.__sql.execute(
                    u"select * from tasks where task regexp ?", 
                    (regexp,)).fetchall())
        if ids == None and regexp == None:
            with self.__sql:
                tasks.extend(self.__sql.execute(
                    u"select * from tasks").fetchall())


        # Grouping tasks
        if group:
            grouped_tasks = []
            if group_by == "list":
                lists = self.__sql.execute(u"select * from lists").fetchall()
                for l in lists:
                    index = len(grouped_tasks)
                    grouped_tasks.append((l,[]))
                    for t in tasks[:]:
                        if t["list"] == str(l["id"]):
                            grouped_tasks[index][1].append(t)
                            tasks.remove(t) # A task is in one list only
            elif group_by == "tag":
                tags = self.__sql.execute(u"select * from tags").fetchall()
                for tag in tags:
                    index = len(grouped_tasks)
                    grouped_tasks.append((tag,[]))
                    for t in tasks:
                        task_tags = t["tags"].split(",")
                        if str(tag["id"]) in task_tags:
                            grouped_tasks[index][1].append(t)
                            # A task can be in different tags
        else:
            grouped_tasks = tasks

        # Ordering tasks (you can't order tasks if they aren't grouped
        if order and group:
            # Ordering groups
            ordered_tasks = self.__quicksort(list = grouped_tasks, column =
                "priority", group = True)
            
            # Ordering tasks according to the first criterion
            for group, tasks in ordered_tasks:
                tmp = order_by[0].split(":")
                if tmp[0] == "reverse":
                    comparison = ">"
                    attribute = tmp[1]
                else:
                    comparison = "<"
                    attribute = tmp[0]
                self.__quicksort(list = tasks, column = attribute, order =
                        comparison)

                # Ordering tasks according to the rest of the criterion
                ordered_by = [attribute]
                for c in order_by[1:]:
                    l = 0
                    r = 0

                    # Extract attribute and sorting order
                    tmp = c.split(":")
                    if tmp[0] == "reverse":
                        comparison = ">"
                        attribute = tmp[1]
                    else:
                        comparison = "<"
                        attribute = tmp[0]

                    # Sort tasks
                    for i in range(len(tasks) - 1):
                        compare = True
                        for o in ordered_by:
                            if tasks[i][o] != tasks[i+1][o]:
                                compare = False
                        if compare:
                            r = i + 1
                        else:
                            self.__quicksort(list = tasks, left = l, right = r,
                                    column = attribute, order = comparison)
                            l = i + 1
                    self.__quicksort(list = tasks, left = l, right = r, column =
                            attribute, order = comparison)
                    ordered_by.append(attribute)
        else:
            ordered_tasks = grouped_tasks

        return ordered_tasks

    def add_task(self, text, priority=None, due_date=None, tags=None, list=None, completed=False):
        u"""Add a task to the database with the informations provided. Use
        default informations if None is provided
        params:
            - text (string)
            - priority (int)
            - due_date (float)
            - tags (array<string>)
            - list (string)
            - completed (bool)
        """

        # Set the priority
        if priority == None:
            priority = self.config["default_priority"]
        elif priority > 3:
            priority = 3

        # Set the due date
        if due_date == None:
            due_date = self.config["default_date"]

        # Get the ids of the tags
        if tags == None or tags == []:
            tags.append(self.config["default_tag"])
        tags_copy = []
        for t in tags:
            self.__add_tag_or_list("tags", t, 0)
            tags_copy.append(self.__get_id("tags", t))
        tags = ",".join(tags_copy)

        # Get the id of the list
        if list == None or list == u"":
            list = self.config["default_list"]
        self.__add_tag_or_list("lists", list, 0)
        list = self.__get_id("lists", list)

        # Set completed
        if completed:
            completed = 1
        else:
            completed = 0
        
        # Add the task to the bdd
        with self.__sql:
            self.__sql.execute('insert into tasks values(null, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (text, priority, due_date, tags, list, completed,
                        self.get_time(), self.get_time()))
            self.__sql.commit()
        pass

    def edit_task(self, id, task = None, priority = None, due_date = None, 
            list = None, add_tags = [], remove_tags = [], completed = None):
        u"""Edit the task with the given id.
        params:
            - id (int)
            - task (string)
            - priority (int)
            - due_date (string)
            - list (int)
            - add_tags (array<int>)
            - remove_tags (array<int>)
            - completed (bool)
        """

        with self.__sql:
            t = self.__sql.execute(u'select * from tasks where id=?',
                    (id,)).fetchone()

        if t == None:
            raise WrongTaskId

        if task == None:
            task = t["task"]
        if priority == None:
            priority = t["priority"]
        if due_date == None:
            due_date = t["due_date"]
        if list == None:
            list = t["list"]
        if completed == None:
            completed = t["completed"]
        elif completed:
            completed = 1

        else:
            completed = 0

        # Process add_tags and remove_tags
        tags = t["tags"].split(",")
        if add_tags != []:
            for tag in add_tags:
                if not str(tag) in tags:
                    tags.append(str(tag))
        if remove_tags != []:
            for tag in remove_tags:
                if str(tag) in tags:
                    tags.remove(str(tag))
        if tags == []:
            tags = ["1"]
        tags = ",".join(tags)

        with self.__sql:
            self.__sql.execute(u'update tasks set task=?, priority=?, due_date=?, list=?, tags=?, completed=?, last_modified=? where id=?',
                    (task, priority, due_date, list, tags, completed,
                        self.get_time(), t["id"]))
        pass

    def remove_tasks(self, ids):
        u"""Remove tasks by their ids
        params:
            - ids (array<int>)
        """
        with self.__sql:
            for i in ids:
                self.__sql.execute(u'delete from tasks where id=?', (i,))
            self.__sql.commit()
        pass

    def get_tags(self, tags, type_id = True, can_create = False):
        u"""Extract the tags from the database. The parameter tags have to be an
        array with tag names or tag ids. 
        
        If tag names are provided, type_id have to be set to False. 
        
        If type_id is set to False and can_create is set to True, then if a tag
        doesn't exist, it will be created.
        """
        res = []
        for t in tags:
            with self.__sql:
                tag_row = None
                if type_id:
                    tag_row = self.__sql.execute(u'select * from tags where id=?',
                            (t,)).fetchone()
                else:
                    tag_row = self.__sql.execute(u'select * from tags where name=?', 
                            (t,)).fetchone()
                    if can_create and tag_row == None:
                        self.add_tag(t)
                        tag_row = self.__sql.execute(u'select * from tags where name=?', 
                            (t,)).fetchone()
                if tag_row != None:
                    res.append(tag_row)
        return res

    def get_tags_regex(self, regex):
        u"""Extract from the database all the tags that match regex, where regex
        is an expression with * and ? jokers"""
        with self.__sql:
            return self.__sql.execute(u'select * from tags where name regexp ?',
                    (regex,)).fetchall()




    def add_tag(self, name, priority=0):
        u"""Add a tag to the database with a certain priority, and create it if
        it doesn't exist
        params:
            - name (string)
            - priority=0 (int)
        """
        self.__add_tag_or_list("tags", name, priority)
        pass

    def edit_tag(self, id, name = None, priority = None):
        u"""Edit the tag with the given id.
        params:
            - name (string)
            - priority (int)
        """
        with self.__sql:
            tag = self.__sql.execute(u'select * from tags where id=?', (id,)).fetchone()
        
        if tag == None:
            raise WrongTagId

        if name == None:
            name = tag["name"]

        if priority == None:
            priority = tag["priority"]

        with self.__sql:
            self.__sql.execute(u'update tags set name=?, priority=?, last_modified=? where id=?',
                    (name, priority, self.get_time(), tag["id"]))
        pass

    def remove_tags(self, ids):
        u"""Remove tags by their ids. Also update tasks which have these tags.
        param:
            - ids (array<string>)
        """
        with self.__sql:
            # Remove tags
            for i in ids:
                if i != "1": # it's not possible to remove the "notag" tag
                    self.__sql.execute(u'delete from tags where id=?', (i,))

            # Update tasks
            for t in self.__sql.execute(u'select * from tasks'):
                tags = t["tags"].split(",")
                tags_copy = tags[:]
                for i in range(len(tags_copy)):
                    if tags_copy[i] in ids:
                        tags.pop(i)
                if len(tags) == 0:
                    tags.append("1")
                self.__sql.execute(u'update tasks set tags=?, last_modified=? where id=?',
                        (",".join(tags), self.get_time(), t["id"]))
            self.__sql.commit()
        pass

    def get_list(self, list, type_id = True, can_create = False):
        u"""Extract a list from the database. The parameter list has to be a
        list name or a list id. 
        
        If a list name is provided, then type_id has to be set to False.

        If type_id is set to False and can_create is set to True, then if the
        list name provided doesn't exist, it will be created.
        """
        res = None
        with self.__sql:
            if type_id:
                res = self.__sql.execute(u'select * from lists where id=?',
                        (list,)).fetchone()
            else:
                res = self.__sql.execute(u'select * from lists where name=?',
                        (list,)).fetchone()
                if res == None and can_create:
                    self.add_list(list)
                    res = self.__sql.execute(u'select * from lists where name=?',
                            (list,)).fetchone()
        return res

    def get_lists_regex(self, regex):
        u"""Extract from the database the lists that match regex, where regex is
        an expression with * and ? jokers."""
        with self.__sql:
            return self.__sql.execute('select * from lists where name regexp ?',
                    (regex,)).fetchall()
            

    def add_list(self, name, priority=0):
        u"""Add a list to the database with a certain priority and create it if 
        it doesn't exist.
        params:
            - name (string)
            - priority=0 (int)
        """
        self.__add_tag_or_list("lists", name, priority)
        pass

    def edit_list(self, id, name = None, priority = None):
        u"""Edit the list with the given id.
        params:
            - id (int)
            - name (string)
            - priority (int)
        """
        with self.__sql:
            list = self.__sql.execute(u'select * from lists where id=?', (id,)).fetchone()
        
        if list == None:
            raise WrongListId

        if name == None:
            name = list["name"]

        if priority == None:
            priority = list["priority"]

        with self.__sql:
            self.__sql.execute(u'update lists set name=?, priority=?, last_modified=? where id=?',
                    (name, priority, self.get_time(), list["id"]))
        pass
    
    def remove_lists(self, ids):
        u"""Remove lists by their ids. Be careful, when deleting a list, every
        task that it contains will be deleted too.
        param:
            - ids (array<string>)
        """
        with self.__sql:
            for i in ids:
                if i != "1": # It's not possible to remove the "nolist" list
                    # Delete list
                    self.__sql.execute(u'delete from lists where id=?', (i,))
                    # Delete tasks
                    self.__sql.execute(u'delete from tasks where list=?', (i,))
            self.__sql.commit()
        pass

    def get_time(self):
        u"""Return the current timestamp"""
        return time.time()

    def get_lock(self, force = False):
        u"""Acquire the lock for the database. If the lock is already active
        with someone other than us, raise an exception"""
        locked_pid = 0
        try:
            with open(self.config["yatdir"] + "/lock") as lock_file:
                locked_pid = pickle.load(lock_file)
        except IOError:
            locked_pid = self.__pid

        if locked_pid == self.__pid or force:
            with open(self.config["yatdir"] + "/lock", 'w') as lock_file:
                pickle.dump(self.__pid, lock_file)
        else:
            raise ExistingLock, locked_pid
        
        return self.__pid

    def release_lock(self):
        u"""Release the lock for the database then return true. If the lock was
        set up by another program, then do nothing and return false."""
        delete = False
        try:
            with open(self.config["yatdir"] + "/lock") as lock_file:
                if pickle.load(lock_file) == self.__pid:
                    delete = True
        except IOError:
            pass

        if delete:
            os.remove(self.config["yatdir"] + "/lock")

        return delete

    def __add_tag_or_list(self, table, name, priority):
        u"""Add an element "name" to the "table" if it doesn't exist. It is
        meant to be used with table="lists" or table="tags" """
        with self.__sql:
            c = self.__sql.execute('select count(*) as nb from %s where name=?' %
                    table, (name,))
            if c.fetchone()[0] == 0:
                self.__sql.execute('insert into %s values(null, ?, ?, ?, ?)' % table,
                    (name, priority, self.get_time(), self.get_time()))
                self.__sql.commit()

    def __get_id(self, table, name):
        u"""Get the id of the element "name" in "table". It's meant to be used
        with table = "lists" or "tags" """
        with self.__sql:
            res = self.__sql.execute('select id from %s where name=?' % table, (name,))
            return str(res.fetchone()[0])

    def __quicksort(self, list, column, left=None, right=None, order=">=",
            group=False):
        u"""Implementation of the quicksort of database rows. 
        
        The parameter "list" contains database rows or tuples of database rows.
        If a tuple is provided, the ordering will be made on the first element,
        and group has to be set to True.

        The parameters "left" and "right" contain the limits for the sorting
        algorithm.

        The parameter "order" contains the comparison that will be made between
        the elements. It has to be in [">", "<", ">=", "<="].
        """
        # If left and right are not provided, assuming sorting on all the list
        if left == None:
            left = 0
        if right == None:
            right = len(list) - 1

        if right > left:
            pivot = left + (right - left)/2
            pivot = self.__partition(list, column, left, right, pivot, order,
                    group)
            self.__quicksort(list, column, left, pivot - 1, order, group)
            self.__quicksort(list, column, pivot + 1, right, order, group)
        return list

    def __partition(self, list, column, left, right, pivot, order, group):
        u"""Partioning of a list according to a "pivot" and a sorting "order",
        within the "left" and "right" limits. This function is a part of the
        quicksort algorithm.
        """
        pivotValue = list[pivot]
        list[pivot], list[right] = list[right], list[pivot]
        storeIndex = left
        for i in range(left, right):
            swap = False

            if group:
                if self.__compare(column, order, list[i][0][column],
                        pivotValue[0][column]):
                    swap = True
            else:
                if self.__compare(column, order, list[i][column],
                        pivotValue[column]):
                    swap = True

            if swap:
                list[i], list[storeIndex] = list[storeIndex], list[i]
                storeIndex += 1
        list[storeIndex], list[right] = list[right], list[storeIndex]
        return storeIndex

    def __compare(self, column, comparison, val1, val2):
        u"""Compare two values of "column" with "comparison". The attribute
        "column" has to be provided to handle correctly the comparison of the
        "due_date" column. This method is a part of the quicksort algorithm.
        """
        # Construct a datetime if the column is due_date
        if comparison == ">":
            return val1 > val2
        elif comparison == ">=":
            return val1 >= val2
        elif comparison == "<":
            return val1 < val2
        elif comparison == "<=":
            return val1 <= val2
        else:
            raise AttributeError, 'order argument should be in [">", ">=", "<", "<="]'

class WrongTagId(Exception):
    u"""Exception raised when trying to extract a tag that doesn't exist"""
    pass
    
class WrongListId(Exception):
    u"""Exception raised when trying to extract a list that doesn't exist"""
    pass

class WrongTaskId(Exception):
    u"""Exception raised when trying to extract a task that doesn't exist"""
    pass

class ExistingLock(Exception):
    u"""Exception raised when a lock is already set."""
    pass

if __name__ == "__main__":
    raise NotImplementedError