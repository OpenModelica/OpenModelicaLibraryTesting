function toJSON
  input Real parsing, frontend, backend, simcode, templates, build;
  input Boolean buildRes;
  input Real sim=-1.0;
  input Boolean simRes=false;
  input Real diff=-1.0;
  input String diffVars[:] = fill("", 0);
  input Integer numCompared=0;
  output String json;
algorithm
  json := "{
  \"parsing\":"+String(parsing)+",
  \"frontend\":"+(if frontend <> -1.0 then String(frontend) else "null")+",
  \"backend\":"+(if backend <> -1.0 then String(backend) else "null")+",
  \"simcode\":"+(if simcode <> -1.0 then String(simcode) else "null")+",
  \"templates\":"+(if templates <> -1.0 then String(templates) else "null")+",
  \"build\":"+(if build <> -1.0 then String(build) else "null")+",
  \"sim\":"+(if sim <> -1.0 then String(sim) else "null")+",
  \"diff\":"+(if diff <> -1.0 then ("{\"time\":"+String(diff)+",\"vars\":["+sum("\"" + v + (if diffVars[end]==v then "\"" else "\",") for v in diffVars)+"], \"numCompared\": "+String(numCompared)+"}") else "null")+",
  \"phase\":"+(if buildRes then (if simRes then (if diff<>-1 and size(diffVars,1)==0 then "7" else "6") else "5")
               elseif build<>-1 then "4" elseif templates<>-1 then "3" elseif simcode<>-1 then "2" elseif backend<>-1 then "1" else "0")+"
}
";
end toJSON;
