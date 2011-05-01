#-*- coding:utf-8 -*-

u"""
Yat Library

This file contains the classes and functions needed for basic handling
of databases created with an old version of yat.

           DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE 
                   Version 2, December 2004 

 Copyright (C) 2010, 2011
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

from Yat import *
from exceptions import *

import re
import sqlite3

class V0_1:
    def __init__(self, current_lib, db, migration):
        self.migration = migration
        self.enc = current_lib.config 
        self.current_lib = current_lib

        self.config = current_lib.config

        self.__sql = sqlite3.connect(db)
        self.__sql.row_factory = sqlite3.Row
        self.__list_ids = {}
        self.__tag_ids = {}
        self.__task_ids = {}

    def delete_tables(self):
        with self.__sql:
            self.__sql.execute('drop table tasks')
            self.__sql.execute('drop table lists')
            self.__sql.execute('drop table tags')
            self.__sql.commit()

    def get_tasks(self, ids=None, regexp=None):
        if ids == None and regexp == None:
            task_rows = self.__sql.execute('select * from tasks').fetchall()
        else:
            task_rows = set()
            if ids != None:
                for i in ids:
                    with self.__sql:
                        task_rows.add(self.__sql.execute(u'''select * from tasks
                                                        where id=?
                                                        ''', (i,)).fetchone())
            if regexp != None:
                with self.__sql:
                    task_rows |= self.__sql.execute(u'''select * from tasks
                                                    where regexp task ?
                                                    ''', (regexp,)).fetchall()

        tasks =set() 
        self.__list_ids[1] = NoList(self.current_lib)
        self.__tag_ids[1] = NoTag(self.current_lib)
        for r in task_rows:
            try:
                t = task_ids[int(r["id"])]
            except:
                t = Task(self.current_lib)
                t.content = r["task"]
                t.priority = int(r["priority"])
                t.due_date = r["due_date"]
                t.completed = r["completed"]
                t.created = r["created"]
                try:
                    t.list = self.__list_ids[int(r["list"])]
                except:
                    with self.__sql:
                        list_row = self.__sql.execute(u'''select * from lists
                                                    where id=?
                                                    ''', (int(r["list"]),)).fetchone()
                    # Get the list from the up-to-date DB if it exists
                    if not self.migration:
                        try:
                            list_ = self.current_lib.get_list(list_row["name"], False)
                        except WrongName:
                            list_ = List(self.current_lib)
                    else:
                        list_ = List(self.current_lib)
                    if list_.id == None:
                        list_.content = list_row["name"]
                        list_.priority = list_row["priority"]
                        list_.created = list_row["created"]
                    self.__list_ids[int(r["list"])] = list_
                    t.list = list_

                tag_ids = [int(i) for i in r['tags'].split(',')]
                t.tags = []
                for i in tag_ids:
                    try:
                        t.tags.append(self.__tag_ids[i])
                    except:
                        with self.__sql:
                            tag_row = self.__sql.execute(u'''select * from tags
                                                        where id=?''', (i,)).fetchone()
                        if not self.migration:
                            try:
                                tag_ = self.current_lib.get_tag(tag_row['name'], False)
                            except WrongName:
                                tag_ = Tag(self.current_lib)
                        else:
                            tag_ = Tag(self.current_lib)
                        if tag_.id == None:
                            tag_.content = tag_row['name']
                            tag_.priority = tag_row['priority']
                            tag_.created = tag_row['created']
                        self.__tag_ids[i] = tag_
                        t.tags.append(tag_)
                tasks.add(t)
                self.__task_ids[int(r["id"])] = t

        return list(tasks)

    def _get_groups(self, cls, group_ids, get_group, table, ids = None, regexp = None):
        if ids == None and regexp == None:
            with self.__sql:
                group_rows = self.__sql.execute('select * from %s' % table).fetchall()
        else:
            if ids != None:
                for i in ids:
                    with self.__sql:
                        group_rows.append(self.__sql.execute(u'''
                                                            select * from %s 
                                                            where id=?
                                                            ''' % table,
                                                            (i,)).fetchone())
            if regexp != None:
                with self.__sql:
                    group_rows.extend(self.__sql.execute(u'''select * from %s
                                                        where regexp name ?
                                                        ''' % table,
                                                        (regexp,)).fetchall())

        groups = set()
        for r in group_rows:
            try:
                groups.add(group_ids[int(r["id"])])
            except KeyError:
                if not self.migration:
                    try:
                        group_ = get_group(r["name"], False)
                    except WrongName:
                        group_ = cls(self.current_lib)
                else:
                    group_ = cls(self.current_lib)
                if group_.id == None:
                    group_.content = r["name"]
                    group_.priority = r["priority"]
                    group_.created = r["created"]
                group_ids[int(r["id"])] = group_
                groups.add(group_)

        return list(groups)

    def get_lists(self, ids = None, regexp = None):
        return self._get_groups(List, self.__list_ids, self.current_lib.get_list, 'lists',
                                ids, regexp)

    def get_tags(self, ids = None, regexp = None):
        return self._get_groups(Tag, self.__tag_ids,
                                lambda tag, b1, b2: self.current_lib.get_tags([tag],
                                                                         b1,
                                                                         b2)[0],
                                'tags', ids, regexp)

def analyze_db(filename=None, current_lib=None, migration=False):
    u"""Check the version of the database pointed by filename, and return the
    appropriate library.
    
    Raises FileNotFound if "filename" doesn't exists.
    Raises UnknownDBVersion if the database is more recent than the program."""

    # If the file doesn't exist, raise an exception
    if not os.path.isfile(filename):
        raise Yat.FileNotFound

    # Connect to the database
    sql = sqlite3.connect(filename)
    sql.row_factory = sqlite3.Row
    
    # Get the version number of the database
    with sql:
        try:
            version = sql.execute(u"""select value from metadata where
                    key='version'""").fetchone()["value"]
        except sqlite3.OperationalError:
            # The metadata table doesn't exist yet, so it's a v0.1 db file
            version = "0.1"

    # Get the appropriate library
    if version == "0.1":
        lib = V0_1(current_lib, filename, migration)
    elif version == "0.2":
        lib = current_lib
    else:
        # Apparently, the database is more recent than the yat used
        raise UnknownDBVersion

    return lib
