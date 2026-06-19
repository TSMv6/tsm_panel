#include <Rcpp.h>
#include <numeric>
using namespace Rcpp;

// Declare constructors
List createList(DataFrame df_lookup, String keyfield, String ValueField);

List createList_Str(DataFrame df_lookup, String keyfield, String ValueField);

int  find_AB_Index(IntegerVector &avec, IntegerVector &bvec, int a, int b);

int  find_AB_Index2(List alookup, List blookup, int a, int b);

bool Compare_Attributes(DataFrame df, int curr_index, int next_index, CharacterVector fields);

bool Compare_Attributes2(List df, int curr_index, int next_index, CharacterVector fields, bool debug);

int  Get_next_Bnode(List lst_Bfrom, List lst_Bto, 
                    int start_seg_Anode, int current_Anode, int current_Bnode,
                    List Atz, List Bfz, List index_A, List index_B, List uni_bi,
                    List AB_dist, int maxzones, bool debug);

//------------------------------------------------------------------------------------------------
// graphWalk:: Main Program
// Loops over each A-B link, assigns an id to "ID1", marks the database as visited, pulls geometry
//    finds next B node, 
//      if returned is a list (more than one Bnode): then moves to next row of the loop
//      else: pulls next A - B link (index)
//            compares current and next link attributes (for all user-specified fields)
//        IF same then:
//           a) assigns sequence id to "ID2"
//           b) pulls geometry and appends to previous
//       IF not then:
//          c) stops looking for next B node and
//          d) moves to the next A-B link and assigns a new id to "ID1"
//------------------------------------------------------------------------------------------------

// Speed Enhancements:
// Passing of A_lookup (Anode row index) and B_lookup (Bnode row index) can be done here but 
// R's data.table is so much faster in finding row index of A, B compared to looping over two vectors to find the same
// To take advantage of it, two indices are supplied a-index and b-index and a match is run
// The approach dropped runtime from 6 minutes to 0.2 seconds to walk the entire network.


// [[Rcpp::export]]
List graphWalk(DataFrame df_links, DataFrame df_lookup, DataFrame df_merge, 
               DataFrame A_lookup, DataFrame B_lookup, CharacterVector fields, int maxzones, bool debug) {
  
  // Initialize data frame vectors
  IntegerVector avec = df_links["A"];
  IntegerVector bvec = df_links["B"];
  IntegerVector rowvec = df_links["row_id"];
  // IntegerVector rev_dir = df_links["rev_dir"];
  // CharacterVector uni_bi_link = df_links["DIR_TRAVEL"];
  
  // IntegerVector Atz = df_links["T_ZLEV"];
  // IntegerVector Bfz = df_links["F_ZLEV"];
  
  List ret;
  List compare_fields;
  String fname;
  
  // Get all link attributes for all fields to compare
  for(int f = 0; f < fields.length(); ++f) {
    fname = fields[f];
    List c1 = createList(df_links, "row_id", fname);
    compare_fields[fname] = c1;
  }
  
  List Atz = createList(df_links, "row_id", "T_ZLEV");  
  List Bfz = createList(df_links, "row_id", "F_ZLEV");
  List uni_bi = createList(df_links, "row_id", "DIR_TRAVEL_Num");
  
  // Check (AB cs BA fac types) to distinguish between reverse link and loop ramps
  List AB_dist = createList(df_links, "row_id", "FACTYPE");
  
  int n = avec.length();
  int start_seg_Anode, current_Anode, current_Bnode, next_Anode, next_Bnode = 0;
  bool compare_attr = 0;
  
  // NumericVector next_Bs;
  
  // List next_Bs; 
  int nextAB_index = -1 ;
  IntegerVector nextAB_rowids(n);
  
  // List lookup = createList(df_lookup);
  List lst_Bto  = createList(df_lookup, "A" , "bnodes");
  List lst_Bfrom  = createList(df_merge, "B" , "anodes");
  List index_A = createList(A_lookup, "A" , "index_A");
  List index_B = createList(B_lookup, "B" , "index_B");
  
  
  // Set ID1 and ID2 for combined-segment and sub-segment sequence
  IntegerVector visited (n);
  IntegerVector ID1(n);
  IntegerVector ID2(n);
  
  int count_id1 = 0;
  int count_id2 = 0;
  
  // Stop walking to next Bnode, if its an intersection / different attributes 
  bool stop_walking = 0;
  
  // Loop over network links
  for(int r = 0; r < n ; ++r) {
    
    // debug: run first 50 links
    // for(int r = 18; r < 24 ; ++r) {
    
    // debug: selected link 
    // bool debug = 0;
    // int debug_start_row = 110582 ;
    // int debug_end_row = 110582 ;
    // for(int r = (debug_start_row - 1); r < debug_end_row + 1  ; ++r) {
    
    // if(r == 75177) Rcout << count_id1 << " " << count_id2 << std::endl;
    // run below only if this is not visited or visited but not in the list 
    // if((visited[r] == 0) & (rev_dir[r] == 0)) {
    if((visited[r] == 0) & (ID1[r] == 0)) {   
      count_id1 += 1;           // update it
      count_id2  = 1;           // reset it
      visited[r] = 1;           // Mark as visited link
      ID1[r] = count_id1;       // link group sequence
      ID2[r] = 0;               // link segment sequence (alway starts with zero)
      // uni_bi =  uni_bi_link[r]; // direction of the current link 
      current_Anode = avec[r];
      current_Bnode = bvec[r];
      start_seg_Anode = current_Anode;
      
      // reset stop_walking flag
      stop_walking = 0;
      
      // debug: print
      // if(start_seg_Anode == 112844) Rcout << "Start A " << start_seg_Anode << " Current A-B: "<< current_Anode << " -> " << current_Bnode << " row number " << r << std::endl;
      if(debug) Rcout << "================================================================================" << std::endl;
      if(debug) Rcout << "================================================================================" << std::endl;
      if(debug) Rcout << "Start A " << start_seg_Anode << " Current A-B: "<< current_Anode << " -> " << current_Bnode << " row number " << r + 1 << std::endl;
      if(debug) Rcout << "--------------------------------------------------------------------------------" << std::endl;
      // As long as there is next connected link, it is not an intersection and the attributes are same
      while((lst_Bto[current_Bnode - 1] != R_NilValue) & (stop_walking == 0)){
        
        // if(debug) Rcout << "reached line 130 " << std::endl;
        
        // skip centroid connectors
        if((current_Anode <= maxzones) | (current_Bnode <= maxzones)){
          next_Bnode = 0;
          if(debug) Rcout << "Centroid connector " << next_Bnode << std::endl;
        } else {
          // Apply search criteria for next B node
          if(debug) Rcout << "--------------------------------------------------------------------------------" << std::endl;
          if(debug) Rcout << "Start A " << start_seg_Anode << " Current A-B: "<< current_Anode << " -> " << current_Bnode << " next_node "<< next_Bnode << " row number " << r + 1 << std::endl;
          
          next_Bnode = Get_next_Bnode(lst_Bfrom, lst_Bto, start_seg_Anode,
                                      current_Anode, current_Bnode, Atz, Bfz,
                                      index_A,  index_B, uni_bi, AB_dist, maxzones, debug); 
          
        }
        
        // if(debug) Rcout << "next B-node " << next_Bnode << std::endl;
        
        if(next_Bnode == 0) {
          if(debug) Rcout << "Stopped at Intersection: " << current_Bnode << std::endl;
          stop_walking = 1;
          
        } else {
          
          // move to next link
          next_Anode = current_Bnode;
          
          // find index of next A-B (find_AB_Index() took 6 mins, find_AB_Index2 takes 0.2 seconds)
          nextAB_index = find_AB_Index2(index_A, index_B, next_Anode, next_Bnode);
          
          if(debug) Rcout << "nextAB_index " << nextAB_index << std::endl;
          
          // compare all attributes between current and next links
          if(debug) Rcout << std::endl << " ------ Link property (Attribute) comparison ------" << std::endl;
          
          compare_attr = Compare_Attributes2(compare_fields, r, (nextAB_index - 1), fields, debug);
          
          if(debug) Rcout << "compare_attr " << compare_attr << std::endl ;
          
          // if attributes are different
          if(compare_attr == 0){
            
            stop_walking = 1;
            if(debug) Rcout << "link attributes not same, Stopped at B-node:  " << current_Bnode << std::endl << std::endl;
          } else {
            
            // update flags & ids for this link group and sequence ids
            visited[nextAB_index - 1] = 1;
            ID1[nextAB_index - 1] = count_id1;
            ID2[nextAB_index - 1] = count_id2 ;
            count_id2 += 1;
            
            // Move to next link (update Anode, Bnode)
            current_Anode = current_Bnode;
            current_Bnode = next_Bnode;
            
            if(debug) Rcout << "link attributes match, continue to next link A-B:  " << current_Anode << " - " << next_Bnode << std::endl << std::endl;
          }
          
        }
        
      } // end stop_walk condition  
      
      // Print message for every 10,000 rows
      if((r > 0) & (r % 10000 == 0)) {
        Rcout << "Processing "<< r << " of " << n << std::endl;
      }
      
    } // end visited condition
    
  } // end link loop
  // 
  // Rcerr << " something went wrong here -- " << std::endl;
  
  ret["ID1"] = ID1;
  ret["ID2"] = ID2;
  ret["next_row"] = nextAB_rowids;
  ret["visited"] = visited;
  
  return ret ;
  
}


// subsetting function
// [[Rcpp::export]]
IntegerVector subset(IntegerVector x, int Anode) {
  
  IntegerVector res;
  
  if(x.length() > 1){
    for(IntegerVector::iterator it = x.begin(); it != x.end(); ++it) {
      if(*it != Anode) {
        res.push_back(*it);
      }
    }
  } else {
    res = x;
  }
  
  return res;
}


// Intersection Search Criteria Algorithm
// [[Rcpp::export]]
int Get_next_Bnode(List lst_Bfrom, List lst_Bto, 
                   int start_seg_Anode, int current_Anode, int current_Bnode,
                   List Atz, List Bfz, List index_A, List index_B, List uni_bi,
                   List AB_dist , int maxzones,
                   bool debug){
  
  int next_Bnode = 0;
  int curr_dir, other_dir  = 0;
  IntegerVector next_Bs;
  IntegerVector next_Bs_rmAnode;
  IntegerVector prev_As;
  IntegerVector prev_As_rmBnode;
  
  // IntegerVector prev_As_unique;
  int a_tz, a_tz2, b_fz, a_fz, b_tz = 0;
  int prev_index, curr_index, next_index = 0;
  int prev_A;
  int ab_dist, ba_dist = 0; 
  int overpass_intersection = 0;
  
  bool is_centriod_connector = 0;
  bool overpass = 0;
  bool mergeNode = 0;
  bool loop_ramp = 0;
  
  // bool debug = 1;
  
  // skip consolidating centroid connectors
  if((current_Anode <= maxzones) | (current_Bnode <= maxzones)) {
    is_centriod_connector = 1;
    if(debug) Rcout << "Centroid connector A: " << current_Anode << " B: " << current_Bnode << std::endl ;
  }
  
  // get list of FROM nodes from B
  if((is_centriod_connector == 0) & (lst_Bfrom[current_Bnode - 1] != R_NilValue)) {
    
    // Get current link attributes
    curr_index = find_AB_Index2(index_A, index_B, current_Anode, current_Bnode);
    a_tz = Atz[curr_index - 1]; 
    curr_dir = uni_bi[curr_index - 1];
    ab_dist = AB_dist[curr_index - 1]; 
    
    prev_As = lst_Bfrom[current_Bnode - 1];
    // if(debug) Rcout << "Line 283 -- is overpass:"<< overpass << std::endl;
    // Bi-directional Links: check if directional link and remove Anode (removes reverse link Anode -> Bnode)
    if(prev_As.length() > 1) {
      // if((curr_dir == 0) & (prev_As.length() > 1)) {  
      // get current link "To" node elevation
      prev_As_rmBnode = subset(prev_As, current_Anode);
      // if(debug) Rcout << "Line 289 -- is overpass:"<< overpass << std::endl;
      // check if any of the links match to current link grade at Bnode (To)?
      for(int x = 0; x < prev_As_rmBnode.length(); ++x){
        
        prev_index = find_AB_Index2(index_A, index_B, prev_As_rmBnode[x], current_Bnode);
        a_tz2 = Atz[prev_index - 1];
        other_dir = uni_bi[prev_index - 1];
        ba_dist = AB_dist[prev_index - 1];  // // links are of different fac types to identify a loop-ramp
        
        if(debug) Rcout << "Line 295 --  is A- B for overpass ? " <<  prev_As_rmBnode[x] << "-" << current_Bnode << " " << a_tz << " vs " << a_tz2  << " " << overpass << std::endl;
        if(a_tz != a_tz2) {
          // if atleast one is different grade then there must be an overpass
          // NOTE: here it doesn't identify next B node but only flags whether it is an overpass or at-grade intersection
          overpass = 1;  
          // loop_ramp = 0;
          if(debug) Rcout << "Line 301 -- YES, A-B is an overpass :"<< overpass << std::endl;
          if(debug) prev_A = prev_As_rmBnode[x];
          if(debug) Rcout << "Overpass links: current A-B: " << current_Anode << " - "<< current_Bnode << " " ;
          if(debug) Rcout << "Other A-B: " << prev_A << " - " << current_Bnode << std::endl ;
          
        } else{
          if(debug) Rcout << "Line 307 -- is not an overpass, checking for loop-ramp:" << std::endl;
          
          // Merge Node links are of different facility types
          ba_dist = AB_dist[prev_index - 1]; 
          if(debug) Rcout << "Line 323 AB and BA FACTYPES "<< prev_As_rmBnode[x]  << "->"<< current_Bnode << " : " << ab_dist << " and "<< ba_dist <<  std::endl;
          if(ba_dist != ab_dist) {
            // loop_ramp (basically an indicator to stop at this BNode)
            loop_ramp = 1;  // turn this on  
            // loop_ramp = 0; // test
            // next_Bnode = 0;
            if(debug) Rcout << "Line 328 -- YES, is a loop ramp with common start / merge nodes :"<<  prev_As_rmBnode[x] << "->" << current_Bnode << std::endl;
            
          } else {
            // At-grade, check if links are in same dir type (oneway vs twoway)
            if(curr_dir != other_dir){
              next_Bnode = 0;
              overpass = 0;
              loop_ramp = 0;
              if(debug) prev_A = prev_As_rmBnode[x];
              if(debug) Rcout << "Links are not same dir code (oneway vs twoway) " << prev_A << " - " << current_Bnode << std::endl ;
            }
          }
        }
      }
      
      // DEbug
      if(debug) {
        Rcout <<"---- Before removing reverse node ---" << std::endl;
        Rcout << "start_seg_Anode " << start_seg_Anode << " B: " << current_Bnode;
        for(int x = 0; x < prev_As.length(); ++x){
          if(x == 0) Rcout << " prev_As_rmBnode " ; 
          Rcout <<   prev_As[x] << " ";
          if(x + 1  ==  prev_As.length())  Rcout << std::endl;
        }
        
        Rcout <<"---- After removing reverse node ---" << std::endl;
        Rcout << "start_seg_Anode " << start_seg_Anode << " B: " << current_Bnode;
        for(int x = 0; x < prev_As_rmBnode.length(); ++x){
          if(x == 0) Rcout << " prev_As_rmBnode " ;
          Rcout <<   prev_As_rmBnode[x] << " ";
          if(x + 1  ==  prev_As_rmBnode.length())  Rcout << std::endl;
        }
      }
      
    } else{
      // uni-directional link
      prev_As_rmBnode = prev_As;
      if(debug) Rcout << "current link is either uni-directional or a merge node " << std::endl;
    }
    
    //-------------------------------------------------------------------------------------
    // Merge node vs. wrongly coded links (A-> B <- c)
    // get list of TO nodes from B
    if(lst_Bto[current_Bnode - 1] != R_NilValue){
      next_Bs = lst_Bto[current_Bnode - 1];
      // check and remove Anode (removes reverse link Bnode -> Anode)
      if(next_Bs.length() > 1){
        // if(next_Bs_rmAnode.length() > 1){
        next_Bs_rmAnode = subset(next_Bs, current_Anode);
      } else{
        next_Bs_rmAnode = next_Bs;
      }
      
      // } else {
      // find why this is a dead end
      // if(lst_Bto[current_Bnode - 1] == R_NilValue) 
      //    Rcout << "Check dead end (no next node) from B:" << current_Bnode << std::endl;
    }
    
    // Wrong coding (A<->B<->C) 
    if((prev_As_rmBnode.length() == 1) & (next_Bs_rmAnode.length() == 1) & (prev_As_rmBnode[0] == next_Bs_rmAnode[0]) ){
      next_Bnode = next_Bs_rmAnode[0];
      if(debug) Rcout << "wrongly coded links Bi-directional (A->B<-C) A: " << current_Anode << " B: "<< current_Bnode << " C: "<< prev_As_rmBnode[0] << std::endl;
      
      // TODO::Find a way to handle loop ramps
      // Based on distance of A-B not equal to B-A or fac type being different ?
    } 
    
    // Merge node (A<->B<->C , D ->B)
    if((prev_As_rmBnode.length() == 1) & (next_Bs_rmAnode.length() == 1) & (prev_As_rmBnode[0] != next_Bs_rmAnode[0]) ){
      if(current_Anode == prev_As_rmBnode[0]){
        // split node
        next_Bnode = next_Bs_rmAnode[0];
        mergeNode = 0;
        if(debug) Rcout << " From a Split link (A->B->C, D->A) A: " << current_Anode << " B: "<< current_Bnode << " C: "<< next_Bnode << " , D -> B: "<< prev_As_rmBnode[0] << std::endl;
        // Merge node
      } else {
        next_Bnode = 0;
        mergeNode = 1;
        if(debug) Rcout << "Merge link (A->B<-C, D->B) A: " << current_Anode << " B: "<< current_Bnode << " C: "<< next_Bnode << " , D -> B: "<< prev_As_rmBnode[0] << std::endl;
        
      }
      
    }
    if(debug) Rcout << "Line 376 -- is overpass:"<< overpass << std::endl;
    //-------------------------------------------------------------------------------------
    // All directions not a merge node
    if(((overpass != 1) & (prev_As_rmBnode.length() > 1)) | (prev_As_rmBnode == R_NilValue) | (loop_ramp == 1))  {
      // if(((overpass != 1) & (prev_As_rmBnode.length() > 1)) | (prev_As_rmBnode == R_NilValue))  {
      next_Bnode = 0;
      if(debug) Rcout << "Not a merge node " << next_Bnode << std::endl;
    } else {
      if(debug) Rcout << "Line 384 -- Begin Intersection Analysis --" << std::endl;
      // get list of TO nodes from B
      if((lst_Bto[current_Bnode - 1] != R_NilValue) & (mergeNode != 1)){
        next_Bs = lst_Bto[current_Bnode - 1];
        if(debug) Rcout << "Line 388 - next_Bs.length() " << next_Bs.length() << std::endl;
        
        // Uni-directional or bi-directional link
        if(next_Bs.length() == 1){
          if(next_Bnode != current_Anode){
            // check if single prev_As_rmBnode then, is it same as 
            // a) current_anode ? if not at least same as 
            // b) next_Bnode (reverse links)
            // If neither then it's an intersection 
            if((current_Anode == prev_As_rmBnode[0]) | (next_Bs[0] == prev_As_rmBnode[0])) {
              next_Bnode = next_Bs[0];
              if(debug) Rcout << "uni-directional link " << next_Bnode << std::endl;
            } else{
              next_Bnode = 0;
              if(debug) Rcout << "uni-directional link Intersection " << next_Bnode << std::endl;
            }
            
            
          } else{
            next_Bnode = 0;
            if(debug) Rcout << "This should never happen, the next oneway segment is in reverse ? " << next_Bnode << std::endl;
          }
          
        } else{
          
          // check and remove Anode (removes reverse link Bnode -> Anode)
          if(next_Bs.length() > 1){
            // TODO:: check for loop ramps
            // don't consider nextB node same as current A node - only if the lengths are same (meaning reverse link or two-way link)
            // otherwise it is a loop ramp ending at a different grade.
            for(int i = 0; i < next_Bs.length(); ++i) {
              // when the current link starting  (curr_Anode) and next link ending points (next_B) are the same
              if(next_Bs[i] == current_Anode){
                // check for elevation
                curr_index = find_AB_Index2(index_A, index_B, current_Anode, current_Bnode);
                next_index = find_AB_Index2(index_A, index_B, current_Bnode, next_Bs[i]);
                // when the elevations are the same then its the same link or a circular link
                a_fz = Bfz[curr_index - 1] ;
                b_tz = Atz[next_index - 1] ;
                if(a_fz == b_tz) {
                  next_Bs_rmAnode = subset(next_Bs, current_Anode);
                } else{
                  // TODO: Once it's a loop ramp end search here instead of running at-grade check
                  // next_Bnode = 0; 
                  // mergeNode = 1;
                  next_Bs_rmAnode = next_Bs;
                }
              }
            }
            
            
          } else{
            next_Bs_rmAnode = next_Bs;
          }
          
          // check for intersections, if no intersections
          if(next_Bs_rmAnode.length() == 1){
            
            next_Bnode = next_Bs_rmAnode[0];
            if(debug) Rcout << "No Intersection " << next_Bnode << std::endl;
            
          } else{
            
            if(debug) Rcout << "Line 414 - next_Bs_rmAnode.length() " << next_Bs_rmAnode.length() << std::endl;
            
            // check if not at-grade find next Bnode
            curr_index = find_AB_Index2(index_A, index_B, current_Anode, current_Bnode);
            
            a_tz = Atz[curr_index - 1];
            if(debug) Rcout << "current A-B: " << current_Anode << "-" << current_Bnode << " T_ZLEV: " << a_tz << std::endl;
            
            if(a_tz == 0) {
              
              for(int i = 0; i < next_Bs_rmAnode.length(); ++i) {
                // check for loop ramp
                if(next_Bs[i] == current_Anode) {
                    curr_index = find_AB_Index2(index_A, index_B, current_Anode, current_Bnode);
                    next_index = find_AB_Index2(index_A, index_B, current_Bnode, next_Bs[i]);
                    // when the elevations are the different then its a loop ramp
                    a_fz = Bfz[curr_index - 1] ;
                    b_tz = Atz[next_index - 1] ;
                    if(a_fz != b_tz) {
                      next_Bnode = 0; 
                      mergeNode = 1;
                      } 
                  } else {
                    // If overpass Get NextB Node for 
                    if(overpass == 1){
                      curr_index = find_AB_Index2(index_A, index_B, current_Anode, current_Bnode);
                      next_index = find_AB_Index2(index_A, index_B, current_Bnode, next_Bs_rmAnode[i]);
                      a_fz = Bfz[next_index - 1] ;
                      b_tz = Atz[curr_index - 1] ;
                      if(a_fz == b_tz) {
                        next_Bnode = next_Bs_rmAnode[i];  
                        mergeNode = 0;
                        if(debug) Rcout << "Line 512, Line 301 identifies A-B is an overpass :"<< overpass << "nextB node :" << next_Bs[i] << std::endl;
                      } 
                    }
                  } 
                } 
              } else { 
              // Check for over-pass here
              // if(a_tz != 0) {
              for(int i = 0; i < next_Bs_rmAnode.length(); ++i) {
                next_index = find_AB_Index2(index_A, index_B, current_Bnode, next_Bs_rmAnode[i]);
                b_fz = Bfz[next_index - 1];
                if(debug) Rcout << "nextlink A-B elevation at A: " << current_Bnode << "-" << next_Bs_rmAnode[i] << " F_ZLEV: " << b_fz << std::endl;
                // Check which link is the connecting one at overpass
                if(b_fz == a_tz){
                  overpass_intersection += 1;
                  next_Bnode = next_Bs_rmAnode[i];
                }
              }
              
              // TODO: make sure this is still grade separated intesection
              // if there are multiple then it is a overpass merge and set B node as intersection.
              if(overpass_intersection > 1){
                next_Bnode = 0;
                if(debug) Rcout << "Multile links at overpass, could be ramp split or merge at grade:  " << current_Bnode << std::endl;
              }
            } 
          }
        }
      }
    }
  }
  
  // Make sure it is not the first segment A node
  if((start_seg_Anode == next_Bnode) | (current_Anode == next_Bnode)){
    next_Bnode = 0;
  }
  if(debug) Rcout << "Return next_Bnode:  " << next_Bnode << std::endl;
  
  return next_Bnode ;
}



// Function to compare attributes
// [[Rcpp::export]]
bool Compare_Attributes(DataFrame df, int curr_index, int next_index, CharacterVector fields) {
  
  // start as same
  bool areSame = 1;
  String fname;
  
  // for each field
  for(int f = 0; f < fields.length(); ++f) {
    
    fname =  fields[f];
    // TODO: use C++ 11 or higher to use auto
    NumericVector vec = df[fname];
    
    // debug
    //  Rcout << " Field : " << f <<  " curr_value " << vec[curr_index] << " next_value " << vec[next_index] << std::endl;
    
    if(vec[curr_index] != vec[next_index]) areSame = 0;
    
  }
  return areSame ;
  
}  


// Function to compare attributes
// [[Rcpp::export]]
bool Compare_Attributes2(List df, int curr_index, int next_index, CharacterVector fields, bool debug) {
  
  // start as same
  bool areSame = 1;
  String fname;
  int curr_value;
  int next_value;
  
  // bool debug = 0;
  
  // for each field
  for(int f = 0; f < fields.length(); ++f) {
    
    fname =  fields[f];
    // TODO: use C++ 11 or higher to use auto
    List vec = df[fname];
    
    curr_value = vec[curr_index] ;
    next_value = vec[next_index];
    if(curr_value != next_value) areSame = 0;
    
    // debug
    // if (curr_index == 137770){
    if(debug)  Rcout << " Field  " <<  fname.get_cstring() <<  "  : curr_value " << curr_value << " next_value " << next_value << std::endl;
    // if(debug)   std::cout << " Field : " << fname.get_cstring()  <<  " curr_value " << curr_value << " next_value " << next_value << std::endl;
    // if(debug)  Rprintf(" Field : %s,  curr_value : %i,  next_value : %i \n ", fields[f] , curr_value , next_value) ;
    
    // }
  }
  return areSame ;
  
}    


//  Function to lookup list of Bnodes
// NOTE: writes R-Style index starting with 1, to use in R
// NOTE: so, if called in C++ decrement by 1 (index-1)
// [[Rcpp::export]]
List createList(DataFrame df_lookup, String keyfield, String ValueField) {
  NumericVector key = df_lookup[keyfield];
  List value = df_lookup[ValueField];
  List lookup(max(key));
  
  // TODO: Use iterators
  for (int i = 0; i < key.size(); ++i) {
    lookup[key[i] - 1] = value[i];
  }
  
  return lookup;
}

// [[Rcpp::export]]
List createList_Str(DataFrame df_lookup, String keyfield, String ValueField) {
  NumericVector key = df_lookup[keyfield];
  CharacterVector value = df_lookup[ValueField];
  List lookup(max(key));
  
  // TODO: Use iterators
  for (int i = 0; i < key.size(); ++i) {
    lookup[key[i] - 1] = value[i];
  }
  
  return lookup;
}

// Function to find row index for given a, b
// This seems expensive takes about 6 minutes for 350k calls
// NOTE: R-Style, for use in C++ decrement by 1
// [[Rcpp::export]]
int find_AB_Index( IntegerVector &avec, IntegerVector &bvec, int a, int b) {
  int AB_index = 0;
  
  for( IntegerVector::iterator it = avec.begin(), jt = bvec.begin(); it !=  avec.end(); ++it, ++jt) {
    
    if((*it == a) & (*jt == b)) {
      AB_index = (it - avec.begin()) + 1;
    }
  }
  
  return AB_index;
}


// [[Rcpp::export]]
int find_AB_Index2( List alookup, List blookup, int a, int b) {
  
  int AB_index = 0 ;
  bool debug = 0;
  
  // ensure there are no NULLs
  if(((alookup[a - 1]) != R_NilValue) & ((blookup[b - 1]) != R_NilValue)){
    
    if(debug) Rcout << " reached line 523";
    
    NumericVector aindex = alookup[a - 1];
    NumericVector bindex = blookup[b - 1];
    
    // iterator
    for( NumericVector::iterator it = aindex.begin(); it != aindex.end(); ++it ){
      for( NumericVector::iterator jt = bindex.begin(); jt != bindex.end(); ++jt){
        if(*it == *jt) {
          AB_index = *jt;
        }
      }
    }
  } 
  
  if(debug & (AB_index == 0)) Rcout << " no index found, check DT row_ids";
  
  return AB_index;
}
