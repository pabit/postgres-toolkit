#!/usr/bin/env python
# coding: UTF-8

# pt-snap-statements
#
# Copyright(c) 2015-2018 Uptime Technologies, LLC.

import getopt
import os
import sys

import PsqlWrapper
import log


class SnapStatements:
    def build_where_clause(self, where_clause, cond):
        if where_clause is None:
            where_clause = " where "
        else:
            where_clause = where_clause + " and "
        where_clause = where_clause + " " + cond
        return where_clause

    def __init__(self, psql, interval, n_top, debug=False):
        self.debug = debug

        self.psql = psql

        # Max queries to be listed.
        if n_top is None:
            n_top = 10000

        log.debug("version: " + str(self.psql.get_version()))

        if self.psql.get_version() < 9.4:
            queryid1 = ''
            queryid2 = ''
        else:
            queryid1 = 'queryid, '
            queryid2 = 'to_hex(s1.queryid) AS "QUERYID", '

        if self.psql.get_version() < 9.2:
            dirtied1 = ''
            dirtied2 = ''
            blkreadtime1 = ''
            blkreadtime2 = ''
            blkwritetime1 = ''
            blkwritetime2 = ''
        else:
            dirtied1 = ('sum(shared_blks_dirtied) + sum(local_blks_dirtied) '
                        'AS blks_dirtied,')
            dirtied2 = ('( s1.blks_dirtied - coalesce(s2.blks_dirtied,0) )'
                        ' AS "B_DIRT", ')
            blkreadtime1 = ', sum(blk_read_time) AS blk_read_time'
            blkreadtime2 = (', round( (s1.blk_read_time - '
                            'coalesce(s2.blk_read_time,0))::numeric, 1) '
                            'AS "R_TIME"')
            blkwritetime1 = ', sum(blk_write_time) AS blk_write_time'
            blkwritetime2 = (', round( (s1.blk_write_time - '
                             'coalesce(s2.blk_write_time,0))::numeric, 1) '
                             'AS "W_TIME" ')

        self.query = '''
/*SNAP*/ CREATE TEMP TABLE snap_pg_stat_statements
    AS SELECT userid,
              dbid,
              {0} /* query_id */
              query,
              sum(calls) AS calls,
              sum(total_time) AS total_time,
              sum(rows) AS rows,
              sum(shared_blks_hit) + sum(local_blks_hit) AS blks_hit,
              sum(shared_blks_read) + sum(local_blks_read)
                + sum(temp_blks_read) AS blks_read,
              {1} /* blks_dirtied */
              sum(shared_blks_written) + sum(local_blks_written)
                + sum(temp_blks_written) AS blks_written
              {2} /* blk_read_time */
              {3} /* blk_write_time */
         FROM pg_stat_statements
        GROUP BY userid,dbid, {0} query;
'''.format(queryid1, dirtied1, blkreadtime1, blkwritetime1)

        self.query = self.query + '''
/*SNAP*/ SELECT pg_sleep(%d);
'''.format(interval)

        self.query = self.query + '''
/*SNAP*/ CREATE TEMP TABLE snap_pg_stat_statements2
    AS SELECT userid,
              dbid,
              {0} /* queryid */
              query,
              sum(calls) AS calls,
              sum(total_time) AS total_time,
              sum(rows) AS rows,
              sum(shared_blks_hit) + sum(local_blks_hit) AS blks_hit,
              sum(shared_blks_read) + sum(local_blks_read)
                + sum(temp_blks_read) AS blks_read,
              {1} /* blks_dirtied */
              sum(shared_blks_written) + sum(local_blks_written)
                + sum(temp_blks_written) AS blks_written
              {2} /* blk_read_time */
              {3} /* blk_write_time */
         FROM pg_stat_statements
        GROUP BY userid,dbid, {0} query;
'''.format(queryid1, dirtied1, blkreadtime1, blkwritetime1)

        self.query = self.query + '''
SELECT u.usename AS "USER",
       d.datname AS "DBNAME",
       {0}
       substring(s1.query, 1, 30) AS "QUERY",
       ( s1.calls - coalesce(s2.calls,0) ) AS "CALLS",
       ( s1.total_time - coalesce(s2.total_time,0) )::integer AS "T_TIME",
       ( s1.rows - coalesce(s2.rows,0) ) AS "ROWS",
       ( s1.blks_hit - coalesce(s2.blks_hit,0) ) AS "B_HIT",
       ( s1.blks_read - coalesce(s2.blks_read,0) ) AS "B_READ",
       {1} /* blks_dirtied */
       ( s1.blks_written - coalesce(s2.blks_written,0) ) AS "B_WRTN"
       {2} /* blk_read_time */
       {3} /* blk_write_time */
  FROM snap_pg_stat_statements2 AS s1
       LEFT OUTER JOIN snap_pg_stat_statements s2 ON s1.userid = s2.userid
           AND s1.dbid = s2.dbid
           AND s1.query = s2.query
       LEFT OUTER JOIN pg_database d ON s1.dbid = d.oid
       LEFT OUTER JOIN pg_user u ON s1.userid = u.usesysid
 WHERE ( s1.calls - coalesce(s2.calls,0) ) > 0
   AND s1.query NOT LIKE \'--%%\'
   AND s1.query NOT LIKE \'/*SNAP*/ %%\'
 ORDER BY 6 DESC
 LIMIT {4};
'''.format(queryid2, dirtied2, blkreadtime2, blkwritetime2, n_top)

    def check(self):
        query = ' \
select count(*) as "pg_stat_statements" \
  from pg_class c left outer join pg_namespace n \
         on c.relnamespace = n.oid \
 where n.nspname=\'public\' \
   and c.relname=\'pg_stat_statements\''

        rs = self.psql.execute_query(query)
        log.debug("check: " + str(rs))

        if int(rs[1][0]) != 1:
            log.error("pg_stat_statements view not found.")
            return False

        query = ' \
select count(*) as "track_io_timing"\
  from pg_settings \
 where name = \'track_io_timing\' \
   and setting = \'on\''

        rs = self.psql.execute_query(query)
        log.debug("check: " + str(rs))

        if self.psql.get_version() >= 9.2 and int(rs[1][0]) != 1:
            log.warning("track_io_timing is diabled.")

        return True

    def reset(self):
        query = 'SELECT pg_stat_statements_reset();'

        rs = self.psql.execute_query(query)
        log.debug("reset: " + str(rs))

        if len(rs) == 0 or rs[0][0] != 'pg_stat_statements_reset':
            log.error("Cannot reset.")
            log.error("Check your privilege and database.")

        return True

    def get(self):
        if self.check() is False:
            return False

        log.debug("get: " + self.query)

        rs = self.psql.execute_query(self.query)

        avail = False
        rs2 = []
        for r in rs:
            if r[0] == 'USER':
                avail = True
            if avail is True:
                rs2.append(r)

        log.debug("get: " + str(rs2))

        self.psql.print_result(rs2)

        return True


def usage():
    print '''
Usage: {0} [option...] [interval]

Options:
    -h, --host=HOSTNAME        Host name of the postgres server
    -p, --port=PORT            Port number of the postgres server
    -U, --username=USERNAME    User name to connect
    -d, --dbname=DBNAME        Database name to connect

    -t, --top=NUMBER           Number of queries to be listed
    -R, --reset                Reset statistics

    --help                     Print this help.
'''.format(os.path.basename(sys.argv[0]))


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "h:p:U:d:Rt:",
                                   ["help", "debug", "host=", "port=",
                                    "username=", "dbname=",
                                    "reset", "top="])
    except getopt.GetoptError, err:
        log.error(str(err))
        usage()
        sys.exit(2)

    host = None
    port = None
    username = None
    dbname = None
    n_top = None

    do_reset = False

    debug = None

    for o, a in opts:
        if o in ("-h", "--host"):
            host = a
        elif o in ("-p", "--port"):
            port = int(a)
        elif o in ("-U", "--username"):
            username = a
        elif o in ("-d", "--dbname"):
            dbname = a
        elif o in ("-R", "--reset"):
            do_reset = True
        elif o in ("-t", "--top"):
            n_top = int(a)
        elif o in ("--debug"):
            log.setLevel(log.DEBUG)
            debug = True
        elif o in ("--help"):
            usage()
            sys.exit(0)
        else:
            log.error("unknown option: " + o + "," + a)
            sys.exit(1)

    p = PsqlWrapper.PsqlWrapper(host=host, port=port, username=username,
                                dbname=dbname, on_error_stop=True, debug=debug)

    if do_reset is True:
        log.info("Resetting statistics.")
        snap = SnapStatements(p, 0, 0, debug=debug)
        snap.reset()
        sys.exit(0)

    try:
        if (len(args) == 0):
            log.info("Interval is 10 seconds.")
            interval = 10
        else:
            interval = int(args[0])
    except ValueError, err:
        log.error(str(err))
        usage()
        sys.exit(2)

    snap = SnapStatements(p, interval, n_top, debug=debug)
    try:
        if snap.get() is False:
            sys.exit(1)
    except KeyboardInterrupt, err:
        log.info("Terminated.")
        sys.exit(1)

    sys.exit(0)
