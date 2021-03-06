import sys
import itertools
import simplejson as json
import subprocess
import os

import numpy as N
import networkx as nx

from pathfinder import PathFinder
from novelty_simple import novelty
from radiotool.composer import Composition, Track, Segment


def changepoint_path(wav_fn, length, graph=None, markers=None,
    sim_mat=None, avg_duration=None, APP_PATH=None, nchangepoints=4,
    min_start=None):
    """wave filename and graph from that wav, length in seconds"""
    # generate changepoints
    try:
        cpraw = subprocess.check_output([
            APP_PATH + 'music_changepoints/novelty',
            wav_fn, '64', 'rms', 'euc', str(nchangepoints) * 3])
        tmp_changepoints = [float(c) for c in cpraw.split('\n') if len(c) > 0]
        changepoints = []
        cp_idx = 0
        while len(changepoints) < nchangepoints:
            if min_start is None:
                changepoints.append(tmp_changepoints[cp_idx])
            elif tmp_changepoints[cp_idx] >= min_start:
                changepoints.append(tmp_changepoints[cp_idx])
            cp_idx += 1

    except:
        changepoints = novelty(wav_fn, k=64, nchangepoints=nchangepoints)

    print "Change points", changepoints

    if graph is not None:
        edge_lens = [graph[e[0]][e[1]]["duration"]
                     for e in graph.edges_iter()]
        avg_duration = N.mean(edge_lens)
        nodes = sorted(graph.nodes(), key=float)
    else:
        nodes = map(str, markers)

    node_count = int(float(length) / avg_duration)    

    closest_nodes = []
    node_to_cp = {}
    for cp in changepoints:
        closest_nodes.append(
            N.argmin([N.abs(float(node) - float(cp)) for node in nodes]))
        node_to_cp[str(closest_nodes[-1])] = cp


    out = []

    for pair in itertools.permutations(closest_nodes, r=2):
        # print "Finding path for pair", pair, "of length", node_count
        
        avoid_nodes = [cn for cn in closest_nodes if cn != pair[1]]
        # avoid_nodes = closest_nodes
        
        if graph is not None:
            try:
                shortest_path = nx.astar_path_length(graph,
                    nodes[pair[0]], nodes[pair[1]])
                # print "# shortest path:", shortest_path
                if  shortest_path <= node_count:
        
                    pf = PathFinder(graph=graph, start=pair[0],
                                    end=pair[1], length=node_count)
                    res, cost = pf.find(avoid=avoid_nodes)
                    if res is not None:
                        out.append((res, cost))
                        break
            except:
                pass

        else:
            pf = PathFinder(start=pair[0],
                            sim_mat=sim_mat.copy(),
                            end=pair[1],
                            nodes=nodes,
                            length=node_count)
            res, cost = pf.find(avoid=avoid_nodes)
            if res is not None:
                out.append((res, cost, map(lambda x: node_to_cp[str(x)], pair)))

    return out, changepoints

def best_changepoint_path(wav_fn, npz_fn, length, 
    APP_PATH=None, nchangepoints=4, min_start=15):

    basename = os.path.basename(wav_fn)

    npz = N.load(npz_fn)
    markers = npz["markers"]
    sim_mat = npz["cost"]
    avg_duration = npz["avg_duration"][0]

    out, changepoints = changepoint_path(wav_fn, length,
        graph=None,
        markers=markers,
        sim_mat=sim_mat,
        avg_duration=avg_duration,
        APP_PATH=APP_PATH,
        nchangepoints=nchangepoints,
        min_start=15)

    if len(out) > 0:
        best, best_cost, cps = min(out, key=lambda x: x[1])

        nodes = map(str, markers)
        durs = []
        print best[-1], nodes
        for i, b in enumerate(best[:-1]):
            try:
                dur = float(nodes[nodes.index(b) + 1]) - float(b)
            except:
                dur = float(b) - float(nodes[nodes.index(b) - 1])
            durs.append(dur)

        print "BEST PATH:", best
        return best, best_cost, cps, durs

    return [], 0

if __name__ == '__main__':
    wav_fn = sys.argv[1]
    
    basename = os.path.basename(wav_fn)
    
    out_name = sys.argv[4]
    
    graph = None
    markers = None
    sim_mat = None
    avg_duration = None
    
    if sys.argv[2].endswith('json'):
        # read the graph
        graph = nx.read_gml(sys.argv[2], relabel=True)
    elif sys.argv[2].endswith('npz'):
        npz = N.load(sys.argv[2])
        markers = npz["markers"]
        sim_mat = npz["cost"]
        avg_duration = npz["avg_duration"][0]


    out, changepoints = changepoint_path(wav_fn, sys.argv[3],
        graph=graph,
        markers=markers, sim_mat=sim_mat,
        avg_duration=avg_duration,
        APP_PATH="../")

    if len(out) > 0:
        best, best_cost = min(out, key=lambda x: x[1])

        # render a few of them

        # handle music authored per beat
        starts = map(float, best)
        nodes = map(str, markers)
        
        if graph is not None:        
            durs = [graph[best[i]][best[i + 1]]["duration"]
                    for i in range(len(best) - 1)]
        else:
            durs = []
            for i, b in enumerate(best[:-1]):
                dur = float(nodes[nodes.index(b) + 1]) - float(b)
                durs.append(dur)

        # for post-padding
        durs.append(12.0)

        if graph is not None:
            dists = [graph[best[i]][best[i + 1]]["distance"]
                     for i in range(len(best) - 1)]
        else:
            dists = []
            for i, b in enumerate(best[:-1]):
                if nodes[nodes.index(b) + 1] == best[i + 1]:
                    dists.append(0)
                else:
                    dists.append(1)

        dists.append(0)

        print "BEST COST", best_cost

        score_start = 12.0
        track = Track(wav_fn, wav_fn)
        c = Composition(channels=1)
        c.add_track(track)
        c.add_score_segment(
            Segment(track, 0.0, starts[0] - 12.0, 12.0))
        current_loc = float(score_start)

        seg_start = starts[0]
        seg_start_loc = current_loc
        
        cf_durations = []
        
        segments = []

        with open ("tmp-starts", 'w') as tf:
            for i, start in enumerate(starts):
                tf.write('%s,%s,%s\n' % (start, dists[i], durs[i]))

        for i, start in enumerate(starts):
            if i == 0 or dists[i - 1] == 0:
                dur = durs[i]                
                current_loc += dur
            else:
                seg = Segment(track, seg_start_loc,
                    seg_start, current_loc - seg_start_loc)
                c.add_score_segment(seg)
                segments.append(seg)
                
                print "segment added at", seg_start_loc, "start", seg_start, "dur", current_loc - seg_start_loc
                
                # track = Track(wav_fn, wav_fn)
                # c.add_track(track)
                dur = durs[i]
                cf_durations.append(dur)
                
                seg_start_loc = current_loc
                seg_start = start
                                
                current_loc += dur
        
        last_seg = Segment(track, seg_start_loc, seg_start,
            current_loc - seg_start_loc)
        c.add_score_segment(last_seg)
        segments.append(last_seg)
        
        # handle the case where there's a jump before the final frame
        if len(cf_durations) > 0:
            if (cf_durations[-1] == 12.0):
                print "Adjusting last cf duration"
                if len(cf_durations) > 1:
                    cf_durations[-1] = cf_durations[-2]
                else:
                    cf_durations[-1] = .5

        print "cf_durations", cf_durations
        print "segments", segments

        for i, seg in enumerate(segments[:-1]):
            print "crossfading with dur", cf_durations[i]
            c.cross_fade(seg, segments[i + 1], cf_durations[i])

        c.output_score(
            adjust_dynamics=False,
            filename=out_name,
            channels=1,
            filetype='wav',
            separate_tracks=False)
        
        new_track = Track(out_name + ".wav", "woop")
        
        # wav2json on original
        subprocess.call(
            'wav2json -p 2 -s 10000 --channels mid -n -o tmp/wf.json "%s"' %
                 wav_fn, shell=True)
                 
        with open('tmp/wf.json') as f:
            orig_wf_data = json.load(f)["mid"]
            
        # wav2json on new track
        subprocess.call(
            'wav2json -p 2 -s 10000 --channels mid -n -o tmp/wf.json "%s"' %
                out_name + ".wav", shell=True)
            
        with open('tmp/wf.json') as f:
            new_wf_data = json.load(f)["mid"]

        out_json = {
            "transitions": [],
            "changepoints": [float("%.3f" % c) for c in changepoints],
            "origLength": track.duration / float(track.samplerate()),
            "origAudioUrl": "retarget/%s.mp3" % basename.split('.')[0],
            "retargetLength": new_track.duration /\
                float(new_track.samplerate()),
            "retargetAudioUrl": "retarget/%s.mp3" % out_name,
            "origData": orig_wf_data,
            "retargetData": new_wf_data
        }
        
        subprocess.call('lame "%s.wav" "generated/%s.mp3"' %
                        (out_name, out_name), shell=True)
        subprocess.call('lame %s "generated/%s.mp3"' %
                        (wav_fn, basename.split('.')[0]),
                        shell=True)

        print
        print "Changepoints used"
        for i, seg in enumerate(segments[:-1]):
            out_json["transitions"].append(float("%.3f" %
                (segments[i + 1].score_location / float(track.samplerate) ) ))
            print "Transition at %.2f" % (segments[i + 1].score_location /
                float(track.samplerate))
        
        with open("generated/" + out_name + ".json", "w") as f:
            json.dump(out_json, f)
        