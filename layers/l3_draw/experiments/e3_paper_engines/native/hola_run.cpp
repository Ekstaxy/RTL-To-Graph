// HOLA (Kieffer et al., InfoVis 2015) through libdialect: TGLF on stdin, positions and
// orthogonal routes on stdout.
//   out:  N <ext id> <cx> <cy> <w> <h>
//         E <src ext id> <tgt ext id> x,y x,y ...
#include <iostream>
#include <sstream>
#include <string>

#include "libdialect/graphs.h"
#include "libdialect/hola.h"
#include "libdialect/io.h"
#include "libdialect/opts.h"

using namespace dialect;

int main(int argc, char **argv) {
    std::stringstream buf;
    buf << std::cin.rdbuf();
    std::string s = buf.str();
    Graph_SP g = buildGraphFromTglf(s);
    HolaOpts opts;
    if (argc > 1) opts.defaultTreeGrowthDir = static_cast<CardinalDir>(std::stoi(argv[1]));
    doHOLA(*g, opts);
    for (auto &p : g->getNodeLookup()) {
        Node_SP n = p.second;
        Avoid::Point c = n->getCentre();
        auto d = n->getDimensions();
        std::cout << "N " << n->getExternalId() << " " << c.x << " " << c.y << " "
                  << d.first << " " << d.second << "\n";
    }
    for (auto &p : g->getEdgeLookup()) {
        Edge_SP e = p.second;
        std::cout << "E " << e->getSourceEnd()->getExternalId() << " "
                  << e->getTargetEnd()->getExternalId();
        for (auto &pt : e->getRoutePoints()) std::cout << " " << pt.x << "," << pt.y;
        std::cout << "\n";
    }
    return 0;
}
